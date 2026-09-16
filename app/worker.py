import asyncio
import json
import logging
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.adapters.spedy_client import SpedyClient, SpedyError
from app.adapters.spedy_payload import montar_payload_spedy
from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_emissao
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.models import AmbienteEnum, Emissao, Empresa, ProvedorEmissao, StatusEmissao
from nfse_core import (
    CertificateError,
    EventoCancelamentoData,
    RespostaEvento,
    SefinClient,
    SefinError,
    build_dps_xml,
    build_evento_cancelamento_xml,
    ler_resposta_emissao,
    ler_resposta_evento,
    sign_dps,
    sign_evento,
)

logger = logging.getLogger(__name__)


async def _marcar_rejeitada(session: AsyncSession, emissao: Emissao, codigo: str, titulo: str) -> None:
    """Marca a emissao como rejeitada com um erro de origem interna (nao veio
    da SEFIN) e commita. json.dumps evita XML/mensagem de excecao com aspas
    ou barras invertidas quebrando o JSON gravado na coluna `erros`."""
    emissao.status = StatusEmissao.rejeitada
    emissao.erros = json.dumps([{"codigo": codigo, "titulo": titulo}], ensure_ascii=False)
    await session.commit()


async def _obter_api_key_spedy(empresa: Empresa, settings: Settings) -> tuple[str | None, str | None]:
    """Decifra a API key da Spedy da empresa.

    Devolve (chave, None) em sucesso, ou (None, motivo) quando a empresa nao
    esta provisionada ou a chave nao decifra. O chamador decide o que fazer
    com a falha: nas funcoes de SUBMISSAO (nada foi enviado ainda pra Spedy),
    marcar erro na hora e seguro. Nas funcoes de CONFIRMACAO (a nota ou o
    cancelamento ja foi submetido antes), marcar erro seria arriscado -- a
    nota pode ja estar autorizada/cancelada do lado da Spedy; o certo e so
    logar e tentar de novo depois."""
    if not empresa.spedy_empresa_id or not empresa.spedy_api_key_cifrada:
        return None, "empresa nao esta provisionada na Spedy (edite a empresa para reconfigurar o provedor)"
    try:
        return decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key), None
    except InvalidToken:
        return None, "chave da Spedy cifrada com outra FERNET_KEY (reconfigure o provedor)"


async def _processar_pendente_spedy(
    session: AsyncSession, emissao: Emissao, empresa: Empresa, settings: Settings,
) -> bool:
    api_key, motivo = await _obter_api_key_spedy(empresa, settings)
    if api_key is None:
        await _marcar_rejeitada(session, emissao, "SPEDY_NAO_PROVISIONADA", motivo)
        return True

    try:
        payload = montar_payload_spedy(empresa, emissao)
        cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    except (ValueError, KeyError, TypeError) as exc:
        await _marcar_rejeitada(session, emissao, "DADOS_INVALIDOS", str(exc))
        return True

    try:
        bruta = await cliente.emitir_nfse(payload)
    except SpedyError as exc:
        await cliente.close()
        await _marcar_rejeitada(session, emissao, "TRANSPORTE", str(exc))
        return True
    await cliente.close()

    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        detalhe = (bruta.get("processingDetail") or {}).get("message") or "Spedy recusou a emissao"
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = json.dumps([{"codigo": "SPEDY", "titulo": detalhe}], ensure_ascii=False)
        emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)
    else:
        emissao.spedy_nota_id = bruta.get("id")
        emissao.status = StatusEmissao.aguardando_confirmacao
    await session.commit()
    return True


async def processar_uma_pendente(session: AsyncSession, settings: Settings | None = None) -> bool:
    """Processa uma emissao 'pendente' (se houver). Retorna True se processou.

    Usa SELECT ... FOR UPDATE SKIP LOCKED: seguro mesmo com mais de um
    worker rodando ao mesmo tempo, cada um pega uma linha diferente.
    """
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.pendente)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)

    if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
        return await _processar_pendente_spedy(session, emissao, empresa, settings)

    # Linha pendente que JA tem dps_id = uma tentativa anterior chegou a
    # submeter a DPS e o processo morreu antes de gravar o resultado. Nesse
    # caso NAO se reenvia as cegas (ARMADILHAS.md item 12) — pergunta-se
    # primeiro a SEFIN se aquela DPS ja virou nota.
    ja_submetida = emissao.dps_id is not None

    try:
        # `decifrar` levanta cryptography.fernet.InvalidToken quando o
        # ciphertext nao bate com a FERNET_KEY atual (chave rotacionada, linha
        # cifrada com outra chave, dado corrompido). InvalidToken herda direto
        # de Exception — NAO e ValueError — entao precisa estar dentro do try
        # e listada explicitamente no except, senao ela escapa daqui,
        # atravessa o `while True` de loop_worker e derruba o worker inteiro:
        # o certificado mal cifrado de UMA empresa pararia a emissao de TODAS.
        pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
        senha = (
            decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
            if empresa.certificado_senha_cifrada
            else None
        )

        dados = DadosEmissao(
            tomador_cpf_cnpj=emissao.tomador_cpf_cnpj,
            tomador_nome=emissao.tomador_nome,
            tomador_email=emissao.tomador_email,
            descricao=emissao.descricao,
            valor=emissao.valor,
            competencia=emissao.competencia,
            dh_emi=emissao.dh_emi_original,
        )
        dps_data = montar_dps_data(empresa, emissao.serie, emissao.numero, dados)

        xml = build_dps_xml(dps_data)
        assinado = sign_dps(xml, pfx_base64, senha)
        emissao.xml_dps = assinado

        # O dps_id e gravado ANTES da chamada a SEFIN, de proposito: se o
        # processo morrer (ou a conexao cair) entre a resposta da SEFIN e o
        # commit final, o banco ja sabe qual DPS foi submetida e a proxima
        # tentativa consulta em vez de reenviar. O dps_id e deterministico
        # (municipio + CNPJ + serie + numero), entao recalcula-lo aqui produz
        # exatamente o mesmo valor da tentativa anterior.
        emissao.dps_id = dps_data.dps_id
        await session.commit()
        # O commit acima solta a trava do SELECT ... FOR UPDATE; readquire
        # para o resto do processamento continuar exclusivo desta linha.
        await session.execute(select(Emissao).where(Emissao.id == emissao.id).with_for_update())

        # AmbienteEnum(...) normaliza tanto o enum quanto o str puro que o
        # SQLAlchemy devolve apos um session.get() (coluna e String, nao um
        # Enum do SQLAlchemy — .value direto em cima do valor recem-carregado
        # do banco quebra com AttributeError; ver Task 5).
        cliente = SefinClient(
            AmbienteEnum(empresa.ambiente).value, pfx_base64, senha,
            municipio_ibge=empresa.municipio_ibge,
        )
        try:
            bruta = None
            if ja_submetida:
                try:
                    previa = await cliente.consultar_dps(emissao.dps_id)
                except SefinError as exc:
                    # Nao da para saber se aquela DPS virou nota. Reenviar as
                    # cegas arrisca gravar como rejeitada (E0202, duplicada)
                    # uma nota que foi autorizada — melhor registrar para
                    # reconciliacao manual.
                    await _marcar_rejeitada(
                        session, emissao, "CONSULTA_DPS",
                        f"nao foi possivel confirmar na SEFIN se a DPS {emissao.dps_id} "
                        f"ja virou nota: {exc}",
                    )
                    return True
                if ler_resposta_emissao(previa).autorizada:
                    bruta = previa
            if bruta is None:
                bruta = await cliente.emitir_dps(assinado)
        finally:
            await cliente.close()
    except SefinError as exc:
        # Falha de transporte/infra: SEFIN fora do ar, timeout, DNS, resposta
        # nao-JSON. So esta linha falha — a fila continua para as outras.
        await _marcar_rejeitada(session, emissao, "TRANSPORTE", str(exc))
        return True
    except (CertificateError, InvalidToken, ValueError) as exc:
        # CertificateError (PFX invalido/senha errada/certificado vencido —
        # nfse_core/signer.py, ex.: certificado expirado apos 1 ano, evento
        # esperado), InvalidToken (certificado cifrado com outra FERNET_KEY) e
        # ValueError (build_dps_xml recusando dados da propria linha: CNPJ do
        # prestador ausente, IBGE invalido, valor <= 0, doc do tomador mal
        # formado) sao todos problemas ISOLADOS desta emissao/empresa, nao da
        # infraestrutura. Sem este except, qualquer um deles escapa de
        # processar_uma_pendente, atravessa o `while True` de loop_worker e
        # derruba o processo do worker inteiro — parando a emissao de TODAS as
        # empresas que compartilham o worker, nao so a que tem o certificado
        # vencido ou o CNPJ mal cadastrado. CertificateError ja e subclasse de
        # ValueError; agrupar tudo no mesmo except evita duplicar o tratamento
        # sem alargar o escopo real (todos sao "recuse esta linha", nunca
        # "derrube o processo").
        detalhe = str(exc) or (
            "certificado cifrado desta empresa nao pode ser decifrado com a "
            "FERNET_KEY atual (recadastre o certificado)"
        )
        await _marcar_rejeitada(session, emissao, "CERTIFICADO_OU_DADOS", detalhe)
        return True

    resultado = ler_resposta_emissao(bruta)
    if resultado.autorizada:
        emissao.status = StatusEmissao.autorizada
        emissao.chave_acesso = resultado.chave_acesso
        emissao.xml_nfse = resultado.xml_nfse
    else:
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = resultado.erros_json()
        # Resposta crua gravada (nao so logada): o catalogo de erros so
        # conhece os nomes de campo da SEFIN Nacional. Endpoints proprios de
        # municipio (ex.: Belem) podem usar chaves diferentes pra
        # codigo/descricao, e sem isso a mensagem chega vazia na tela sem
        # pista de por que — o JSON bruto fica disponivel pra exportar como
        # evidencia junto a prefeitura.
        emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)
        logger.warning("emissao %s rejeitada; resposta bruta: %s", emissao.id, bruta)

    await session.commit()
    return True


async def processar_uma_aguardando_confirmacao_spedy(
    session: AsyncSession, settings: Settings | None = None,
) -> bool:
    """Consulta o resultado final de uma emissao Spedy ainda pendente de
    confirmacao. So conta como "trabalho feito" (True) quando o status vira
    terminal -- assim o loop respeita o intervalo normal entre tentativas em
    vez de martelar a Spedy sem pausa enquanto a nota ainda processa.
    Ordenado por atualizada_em (nao criada_em): uma linha que nunca resolve
    nao pode monopolizar a fila pra sempre -- cada tentativa de poll atualiza
    atualizada_em mesmo sem resolver, fazendo a fila rotacionar."""
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.aguardando_confirmacao)
        .order_by(Emissao.atualizada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)
    api_key, motivo = await _obter_api_key_spedy(empresa, settings)
    if api_key is None:
        logger.warning(
            "nao foi possivel obter a chave Spedy da empresa %s pra confirmar a emissao %s: %s",
            empresa.id, emissao.id, motivo,
        )
        # Bump em atualizada_em mesmo sem resolver: sem isso, uma chave
        # permanentemente nao-decifravel (ex.: FERNET_KEY rotacionada no meio
        # de uma confirmacao pendente) deixa esta linha sempre a mais antiga
        # em atualizada_em, sendo repescada pra sempre e reabrindo a fome de
        # fila que o ORDER BY atualizada_em existe pra evitar.
        emissao.atualizada_em = datetime.now(timezone.utc)
        await session.commit()
        return False

    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        bruta = await cliente.consultar_nfse(emissao.spedy_nota_id)
    except SpedyError as exc:
        await cliente.close()
        logger.warning("falha ao consultar emissao %s na Spedy: %s", emissao.id, exc)
        return False
    await cliente.close()

    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        logger.warning(
            "Spedy devolveu HTTP %s ao consultar a emissao %s (nota %s); tentando de novo depois",
            http_status, emissao.id, emissao.spedy_nota_id,
        )
        emissao.atualizada_em = datetime.now(timezone.utc)
        await session.commit()
        return False

    status = interpretar_status_emissao(bruta)
    if status == "authorized":
        emissao.status = StatusEmissao.autorizada
        emissao.chave_acesso = chave_acesso_de(bruta)
        await session.commit()
        return True
    if status == "rejected":
        detalhe = bruta.get("processingDetail") or {}
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = json.dumps(
            [{"codigo": detalhe.get("code") or "SPEDY", "titulo": detalhe.get("message") or "Emissao rejeitada pela Spedy"}],
            ensure_ascii=False,
        )
        emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)
        await session.commit()
        return True

    emissao.atualizada_em = datetime.now(timezone.utc)
    await session.commit()
    return False


async def _marcar_erro_cancelamento(session: AsyncSession, emissao: Emissao, codigo: str, titulo: str) -> None:
    emissao.status = StatusEmissao.erro_cancelamento
    emissao.erros = json.dumps([{"codigo": codigo, "titulo": titulo}], ensure_ascii=False)
    await session.commit()


async def _processar_cancelamento_pendente_spedy(
    session: AsyncSession, emissao: Emissao, empresa: Empresa, settings: Settings,
) -> bool:
    api_key, motivo = await _obter_api_key_spedy(empresa, settings)
    if api_key is None:
        await _marcar_erro_cancelamento(session, emissao, "SPEDY_NAO_PROVISIONADA", motivo)
        return True

    try:
        cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    except ValueError as exc:
        await _marcar_erro_cancelamento(session, emissao, "DADOS_INVALIDOS", str(exc))
        return True

    try:
        bruta = await cliente.cancelar_nfse(emissao.spedy_nota_id, emissao.motivo_cancelamento or "")
    except SpedyError as exc:
        await cliente.close()
        await _marcar_erro_cancelamento(session, emissao, "TRANSPORTE", str(exc))
        return True
    await cliente.close()

    # cancelar_nfse usa o _handle tolerante da SpedyClient (Task 2) -- NAO
    # levanta SpedyError em 4xx, devolve um dict com _http_status embutido,
    # igual a emitir_nfse. Confirmado ao vivo contra o sandbox: uma nota que
    # nunca foi autorizada devolve 400 sincrono com
    # {"errors": [{"message": "A nota fiscal nao pode ser cancelada."}]} (um
    # `errors` no topo, formato diferente do `processingDetail` da emissao).
    # Sem este check a linha ficava presa para sempre em
    # cancelamento_aguardando_confirmacao, porque consultar_nfse nunca via o
    # status virar "canceled".
    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        detalhe = (bruta.get("errors") or [{}])[0].get("message") or "Spedy recusou o cancelamento"
        await _marcar_erro_cancelamento(session, emissao, "SPEDY", detalhe)
        return True

    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await session.commit()
    return True


async def processar_um_cancelamento_pendente(session: AsyncSession, settings: Settings | None = None) -> bool:
    """Processa uma emissao 'cancelamento_pendente' (se houver). Retorna True se processou.

    Espelha processar_uma_pendente: SELECT ... FOR UPDATE SKIP LOCKED,
    exceptions isoladas por linha (nunca derruba o loop inteiro).
    """
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.cancelamento_pendente)
        .order_by(Emissao.criada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)

    if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
        return await _processar_cancelamento_pendente_spedy(session, emissao, empresa, settings)

    try:
        pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
        senha = (
            decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
            if empresa.certificado_senha_cifrada
            else None
        )

        evento_data = EventoCancelamentoData(
            chave_nfse=emissao.chave_acesso,
            tp_amb=1 if AmbienteEnum(empresa.ambiente) == AmbienteEnum.producao else 2,
            dh_evento=datetime.now(timezone.utc),
            autor_cpf_cnpj=empresa.cnpj,
            x_motivo=emissao.motivo_cancelamento or "",
        )
        xml_evento = build_evento_cancelamento_xml(evento_data)
        assinado = sign_evento(xml_evento, pfx_base64, senha)

        cliente = SefinClient(
            AmbienteEnum(empresa.ambiente).value, pfx_base64, senha,
            municipio_ibge=empresa.municipio_ibge,
        )
        try:
            bruta = await cliente.registrar_evento(emissao.chave_acesso, assinado)
        finally:
            await cliente.close()
    except SefinError as exc:
        await _marcar_erro_cancelamento(session, emissao, "TRANSPORTE", str(exc))
        return True
    except (CertificateError, InvalidToken, ValueError) as exc:
        detalhe = str(exc) or (
            "certificado cifrado desta empresa nao pode ser decifrado com a "
            "FERNET_KEY atual (recadastre o certificado)"
        )
        await _marcar_erro_cancelamento(session, emissao, "CERTIFICADO_OU_DADOS", detalhe)
        return True

    resultado = ler_resposta_evento(bruta)
    if resultado.registrado:
        emissao.status = StatusEmissao.cancelada
        emissao.cancelada_em = datetime.now(timezone.utc)
    else:
        emissao.status = StatusEmissao.erro_cancelamento
        emissao.erros = json.dumps(resultado.erros, ensure_ascii=False)

    await session.commit()
    return True


async def processar_um_cancelamento_aguardando_confirmacao_spedy(
    session: AsyncSession, settings: Settings | None = None,
) -> bool:
    """Espelha processar_uma_aguardando_confirmacao_spedy: o cancelamento na
    Spedy tambem e assincrono (confirmado na doc oficial -- DELETE
    /service-invoices/{id} processa ate o status "canceled"). Mesma logica de
    rotacao por atualizada_em."""
    settings = settings or get_settings()

    stmt = (
        select(Emissao)
        .where(Emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao)
        .order_by(Emissao.atualizada_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)
    api_key, motivo = await _obter_api_key_spedy(empresa, settings)
    if api_key is None:
        logger.warning(
            "nao foi possivel obter a chave Spedy da empresa %s pra confirmar o cancelamento %s: %s",
            empresa.id, emissao.id, motivo,
        )
        # Mesmo motivo do bump em processar_uma_aguardando_confirmacao_spedy:
        # sem isso, uma chave permanentemente nao-decifravel reabre a fome de
        # fila que o ORDER BY atualizada_em existe pra evitar.
        emissao.atualizada_em = datetime.now(timezone.utc)
        await session.commit()
        return False

    cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    try:
        bruta = await cliente.consultar_nfse(emissao.spedy_nota_id)
    except SpedyError as exc:
        await cliente.close()
        logger.warning("falha ao consultar cancelamento %s na Spedy: %s", emissao.id, exc)
        return False
    await cliente.close()

    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        logger.warning(
            "Spedy devolveu HTTP %s ao consultar o cancelamento %s (nota %s); tentando de novo depois",
            http_status, emissao.id, emissao.spedy_nota_id,
        )
        emissao.atualizada_em = datetime.now(timezone.utc)
        await session.commit()
        return False

    if bruta.get("status") == "canceled":
        emissao.status = StatusEmissao.cancelada
        emissao.cancelada_em = datetime.now(timezone.utc)
        await session.commit()
        return True

    emissao.atualizada_em = datetime.now(timezone.utc)
    await session.commit()
    return False


async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
            async with session_factory() as session:
                processou_confirmacao_spedy = await processar_uma_aguardando_confirmacao_spedy(session)
            async with session_factory() as session:
                processou_confirmacao_cancel_spedy = await processar_um_cancelamento_aguardando_confirmacao_spedy(session)
        except Exception:
            # Supervisao do loop, de proposito abrangente: o tratamento fino
            # (por tipo de erro, por linha) mora dentro de
            # processar_uma_pendente/processar_um_cancelamento_pendente. Aqui
            # o unico objetivo e garantir que NENHUMA excecao inesperada —
            # banco reiniciado, conexao derrubada, bug novo — mate o processo
            # e pare a emissao/cancelamento de todas as empresas.
            logger.exception("falha inesperada ao processar fila pendente; o loop continua")
            processou_emissao = False
            processou_cancelamento = False
            processou_confirmacao_spedy = False
            processou_confirmacao_cancel_spedy = False
        if not any([
            processou_emissao, processou_cancelamento,
            processou_confirmacao_spedy, processou_confirmacao_cancel_spedy,
        ]):
            await asyncio.sleep(intervalo_segundos)
