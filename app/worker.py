import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.adapters.nfe_builder import ItemPedido, montar_nfe_data
from app.adapters.spedy_client import SpedyClient, SpedyError
from app.adapters.spedy_payload import montar_payload_spedy
from app.adapters.spedy_resposta import chave_acesso_de, interpretar_status_cancelamento, interpretar_status_emissao
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.models import (
    AmbienteEnum, Cliente, Emissao, EmissaoNfe, Empresa, ItemEmissaoNfe, Produto, ProvedorEmissao, StatusEmissao,
)
from nfe_core import NFE_NS, SefazClient, build_nfe_xml, eh_autorizado, eh_denegado, nao_encontrada, sign_nfe
from nfe_core import AmbienteEnum as AmbienteNfe
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

# Reemissao automatica com backoff, pra fila grande (1300+ notas, 30/09) nao
# depender de clicar "Reemitir" nota por nota. So 3 tentativas AUTOMATICAS
# (indice 0, 1, 2 abaixo) -- depois disso fica rejeitada esperando acao
# manual, igual antes. Sem harm em tentar de novo mesmo em erro de negocio
# "permanente" (E0160 etc.): o pior caso e so gastar as 3 tentativas a toa,
# nao ha risco de duplicar nem corromper nada (dps_id reutilizado consulta
# antes de reenviar, ver `ja_submetida` em processar_uma_pendente). Intervalo
# curto de proposito (nao horas) porque com 1300 notas um backoff longo
# faria o lote inteiro levar dias pra terminar.
MAX_TENTATIVAS_REEMISSAO_AUTOMATICA = 3
_BACKOFF_REEMISSAO_AUTOMATICA = [timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30)]

# Pausa minima entre cada emissao processada pelo worker (nao so quando a
# fila esta vazia) -- evita rajada contra a Spedy/SEFIN quando ha um backlog
# grande (confirmado ao vivo: a Spedy tem limite de rajada por segundo em
# outros endpoints; mais seguro pausar aqui tambem do que descobrir o limite
# de emissao na marra com 1300 notas de uma vez).
PACING_SEGUNDOS = 2.0


def _agendar_proxima_tentativa(emissao: Emissao | EmissaoNfe) -> None:
    """Chamado toda vez que uma emissao e marcada como rejeitada: agenda a
    proxima tentativa automatica (ver processar_reemissao_automatica_pendente)
    se ainda nao estourou o limite. Nao mexe no status -- quem chama decide
    se e StatusEmissao.rejeitada."""
    if emissao.tentativas_reemissao < MAX_TENTATIVAS_REEMISSAO_AUTOMATICA:
        atraso = _BACKOFF_REEMISSAO_AUTOMATICA[emissao.tentativas_reemissao]
        emissao.tentativas_reemissao += 1
        emissao.proxima_tentativa_em = datetime.now(timezone.utc) + atraso
    else:
        emissao.proxima_tentativa_em = None


async def _marcar_rejeitada(session: AsyncSession, emissao: Emissao | EmissaoNfe, codigo: str, titulo: str) -> None:
    """Marca a emissao como rejeitada com um erro de origem interna (nao veio
    da SEFIN) e commita. json.dumps evita XML/mensagem de excecao com aspas
    ou barras invertidas quebrando o JSON gravado na coluna `erros`."""
    emissao.status = StatusEmissao.rejeitada
    emissao.erros = json.dumps([{"codigo": codigo, "titulo": titulo}], ensure_ascii=False)
    _agendar_proxima_tentativa(emissao)
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

    tomador_cliente = await session.get(Cliente, emissao.cliente_id) if emissao.cliente_id else None
    try:
        payload = montar_payload_spedy(empresa, emissao, tomador_cliente)
        cliente = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
    except (ValueError, KeyError, TypeError) as exc:
        await _marcar_rejeitada(session, emissao, "DADOS_INVALIDOS", str(exc))
        return True

    # Grava o payload de saida (sem token/API key -- essa vai so no header via
    # SpedyClient, nunca no corpo) para poder exportar como evidencia em
    # chamados com a Spedy/prefeitura quando uma emissao e rejeitada. Setado
    # ANTES da chamada e no mesmo objeto de sessao para persistir mesmo se
    # emitir_nfse nunca responder (o commit de _marcar_rejeitada no catch
    # abaixo leva junto).
    payload_json = json.dumps(payload, ensure_ascii=False)
    emissao.requisicao_bruta = payload_json
    emissao.ambiente = AmbienteEnum(empresa.ambiente)
    logger.info("emissao %s: payload enviado a Spedy: %s", emissao.id, payload_json)
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
        _agendar_proxima_tentativa(emissao)
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
        emissao.ambiente = AmbienteEnum(empresa.ambiente)

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
        # "nacional" forca o endpoint nacional generico (municipio_ibge=None
        # pula a busca em MUNICIPIO_DPS_URLS dentro do SefinClient); "direto"
        # mantem a auto-deteccao do endpoint proprio do municipio (ex.: Belem).
        municipio_ibge_sefin = (
            None if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.nacional
            else empresa.municipio_ibge
        )
        cliente = SefinClient(
            AmbienteEnum(empresa.ambiente).value, pfx_base64, senha,
            municipio_ibge=municipio_ibge_sefin,
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
        _agendar_proxima_tentativa(emissao)

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
        # Limpa o erro da tentativa REJEITADA anterior (se houve reemissao) --
        # senao uma nota ja autorizada continua mostrando na tela o erro
        # antigo, como se ainda tivesse problema.
        emissao.erros = None
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
        _agendar_proxima_tentativa(emissao)
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

        municipio_ibge_sefin = (
            None if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.nacional
            else empresa.municipio_ibge
        )
        cliente = SefinClient(
            AmbienteEnum(empresa.ambiente).value, pfx_base64, senha,
            municipio_ibge=municipio_ibge_sefin,
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

    # Grava a resposta crua a CADA tentativa, nao so quando finalmente
    # resolve -- uma nota presa em cancelamento_aguardando_confirmacao por
    # dias nao deixava nenhuma evidencia acessivel do que a Spedy estava
    # respondendo de verdade (so log efemero). Agora o botao "Resposta
    # SEFIN" sempre mostra o ultimo estado consultado.
    emissao.resposta_bruta = json.dumps(bruta, ensure_ascii=False)

    http_status = int(bruta.get("_http_status") or 0)
    if http_status >= 400:
        logger.warning(
            "Spedy devolveu HTTP %s ao consultar o cancelamento %s (nota %s); tentando de novo depois",
            http_status, emissao.id, emissao.spedy_nota_id,
        )
        emissao.atualizada_em = datetime.now(timezone.utc)
        await session.commit()
        return False

    status_cancelamento = interpretar_status_cancelamento(bruta)
    if status_cancelamento == "canceled":
        emissao.status = StatusEmissao.cancelada
        emissao.cancelada_em = datetime.now(timezone.utc)
        await session.commit()
        return True
    if status_cancelamento == "failed":
        # A NOTA continua autorizada (interpretar_status_cancelamento so olha
        # processingDetail) -- so o cancelamento em si foi recusado. Sem
        # tratar como terminal, a linha ficava presa "aguardando confirmacao"
        # pra sempre (caso real: mais de 1 dia parada, prazo de cancelamento
        # expirado na prefeitura).
        detalhe = bruta.get("processingDetail") or {}
        await _marcar_erro_cancelamento(
            session, emissao, detalhe.get("code") or "SPEDY",
            detalhe.get("message") or "Cancelamento recusado pela Spedy",
        )
        return True

    emissao.atualizada_em = datetime.now(timezone.utc)
    await session.commit()
    return False


async def processar_reemissao_automatica_pendente(session: AsyncSession) -> bool:
    """Promove UMA emissao rejeitada com tentativa automatica vencida de
    volta pra "pendente" -- processar_uma_pendente cuida do reenvio de
    verdade no proximo tick (mesmo caminho de "Reemitir" manual, inclusive a
    seguranca de consultar a SEFIN antes de reenviar quando ja tem dps_id).
    So flipa o status; nao fala com SEFIN/Spedy aqui."""
    agora = datetime.now(timezone.utc)
    stmt = (
        select(Emissao)
        .where(
            Emissao.status == StatusEmissao.rejeitada,
            Emissao.proxima_tentativa_em.isnot(None),
            Emissao.proxima_tentativa_em <= agora,
        )
        .order_by(Emissao.proxima_tentativa_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    emissao.status = StatusEmissao.pendente
    emissao.proxima_tentativa_em = None
    await session.commit()
    return True


async def _montar_e_assinar_nfe(
    session: AsyncSession, emissao: EmissaoNfe, empresa: Empresa, ambiente: AmbienteEnum, settings: Settings,
) -> tuple[str, bytes]:
    """Monta e assina a NF-e a partir do cadastro ATUAL. Devolve (chave, xml assinado).

    `ambiente` e o da LINHA (congelado na primeira montagem), nunca o atual
    da empresa: o tpAmb do XML tem que bater com a SEFAZ para onde ele vai.

    Roda a cada tentativa que vai enviar (ver processar_uma_pendente_nfe).
    dh_emi = emissao.criado_em (fixo desde a criacao da linha), entao a chave
    -- cUF + AAMM + CNPJ + serie + numero + cNF(serie+numero) -- sai identica
    em toda retentativa, mesmo cruzando a virada do mes. A chave sai do Id do
    infNFe que o proprio build_nfe_xml gravou -- uma unica fonte de verdade,
    sem recalcular chave_de_acesso() separadamente."""
    pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
    senha = (
        decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
        if empresa.certificado_senha_cifrada
        else None
    )
    cliente = await session.get(Cliente, emissao.cliente_id)
    itens_db = (await session.execute(
        select(ItemEmissaoNfe).where(ItemEmissaoNfe.emissao_nfe_id == emissao.id).order_by(ItemEmissaoNfe.id)
    )).scalars().all()
    produtos_por_id = {item.produto_id: await session.get(Produto, item.produto_id) for item in itens_db}
    # valor_unitario do item ja e o preco final resolvido na criacao da
    # emissao (Task 12) -- passado como override pra nao cair no
    # valor_unitario_padrao do produto, que pode ter mudado desde entao.
    itens = [
        ItemPedido(
            produto_id=item.produto_id,
            quantidade=item.quantidade,
            valor_unitario_override=item.valor_unitario,
            aliquota_interna_destino=item.aliquota_interna_destino,
            cfop_override=item.cfop,
        )
        for item in itens_db
    ]
    nfe_data = montar_nfe_data(
        empresa, cliente, emissao.serie, emissao.numero, produtos_por_id, itens,
        dh_emi=emissao.criado_em, ambiente=ambiente,
    )
    assinado = sign_nfe(build_nfe_xml(nfe_data), pfx_base64, senha)
    inf = etree.fromstring(assinado).find(f"{{{NFE_NS}}}infNFe")
    return inf.get("Id")[len("NFe"):], assinado


async def processar_uma_pendente_nfe(session: AsyncSession, settings: Settings | None = None) -> bool:
    """Processa uma NF-e 'pendente' (se houver). Retorna True se processou.

    Mesma semantica de status da NFS-e: `pendente` = fila automatica do
    worker; `aguardando_emissao` = rascunho que o worker ignora.

    Espelha processar_uma_pendente (NFS-e): SELECT ... FOR UPDATE SKIP LOCKED,
    chave gravada ANTES de falar com a SEFAZ, consulta antes de reenviar, erros
    isolados por linha (nunca derruba o loop_worker).

    Mesmo principio da NFS-e: toda tentativa que vai ENVIAR remonta e
    reassina o XML a partir do cadastro ATUAL (itens, precos, CFOP, ICMS,
    certificado) -- assim uma rejeicao por dado corrigivel (NCM, CFOP, preco)
    se resolve corrigindo o cadastro, sem XML congelado. So a chave fica
    estavel, como o dps_id da NFS-e: ela tem AAMM, entao o dh_emi e preso em
    emissao.criado_em (nunca o relogio) e a chave recalculada e identica a de
    qualquer tentativa anterior, mesmo cruzando a virada do mes.

    Ordem numa retentativa (linha ja tem chave): consulta a SEFAZ PRIMEIRO,
    com a chave gravada. Se ja esta autorizada, registra e NAO remonta -- o
    xml_nfe gravado e exatamente o que foi enviado (gravado antes de cada
    envio) e e o que a SEFAZ autorizou; remontar com cadastro alterado
    guardaria um XML diferente do autorizado. Tambem nao depende do
    certificado/cadastro estar OK pra reconhecer uma autorizacao que ja
    aconteceu. Uso denegado (110/301/302) na consulta tambem e final: registra
    a denegacao (com protocolo) sem remontar. So remonta, confere a chave e
    envia quando a SEFAZ responde 217 (chave nao consta na base); qualquer
    outra resposta e inconclusiva -- rejeita a linha com CONSULTA_INCONCLUSIVA
    e deixa o backoff automatico consultar de novo, sem reenviar.

    Rejeicao final: uso denegado e terminal (grava o protocolo da denegacao,
    nao agenda retentativa); demais rejeicoes agendam retentativa automatica.
    """
    settings = settings or get_settings()

    stmt = (
        select(EmissaoNfe)
        .where(EmissaoNfe.status == StatusEmissao.pendente)
        .order_by(EmissaoNfe.criado_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    empresa = await session.get(Empresa, emissao.empresa_id)

    # chave_acesso ja gravada = uma tentativa anterior chegou a montar/assinar
    # (e talvez a submeter) esta NF-e. Nao se reenvia as cegas: pergunta-se
    # primeiro a SEFAZ (mesmo principio do ja_submetida da NFS-e).
    ja_submetida = emissao.chave_acesso is not None

    # Ambiente (homologacao/producao) desta NF-e: congelado na LINHA na
    # primeira montagem (mesmo commit da chave/XML, la embaixo) e nunca mais
    # relido da empresa. empresa.ambiente pode mudar a qualquer momento (PUT
    # /empresas/mim); ler o atual numa retentativa mandaria uma nota de teste
    # pra SEFAZ real, ou consultaria uma nota de producao na SEFAZ de
    # homologacao -- que responde 217 e dispararia reenvio no lugar errado.
    # Mesmo principio de Emissao.ambiente na NFS-e, SEM o fallback pro
    # ambiente atual: toda EmissaoNfe ja nasceu com esta coluna.
    if ja_submetida:
        if emissao.ambiente is None:
            # Invariante quebrada (chave gravada sem ambiente). Cair pro
            # empresa.ambiente reabriria exatamente o risco acima -- nao
            # fala com SEFAZ nenhuma, deixa pra analise manual.
            logger.error("emissao NF-e %s tem chave %s mas nao tem ambiente gravado", emissao.id, emissao.chave_acesso)
            await _marcar_rejeitada(
                session, emissao, "AMBIENTE_DESCONHECIDO",
                f"a NF-e {emissao.chave_acesso} ja foi montada mas nao tem o ambiente "
                "(homologacao/producao) gravado; consulta/reenvio bloqueados",
            )
            return True
        ambiente_emissao = AmbienteEnum(emissao.ambiente)
    else:
        # Primeira montagem: unico momento em que o ambiente vem da empresa.
        # So e persistido junto com chave/XML (abaixo) -- se a montagem
        # falhar, nada foi enviado e a proxima tentativa decide de novo.
        ambiente_emissao = AmbienteEnum(empresa.ambiente)
    ambiente = AmbienteNfe(ambiente_emissao.value)
    cliente_sefaz = SefazClient()

    # O SefazClient nao tem uma excecao propria de transporte: repassa o que
    # o zeep levantar. Por isso o `except Exception` abaixo, escopado SO as
    # chamadas a SEFAZ (nunca ao resto da funcao): qualquer falha nelas e
    # tratada como transporte, isolada nesta linha.
    resposta = None
    if ja_submetida:
        try:
            previa = await cliente_sefaz.consultar_protocolo(emissao.chave_acesso, empresa.uf, ambiente)
        except Exception as exc:
            # Nao da para saber se esta NF-e ja foi autorizada. Reenviar as
            # cegas arrisca gravar como rejeitada (duplicidade) uma nota que
            # foi autorizada -- registra para nova tentativa/reconciliacao.
            await _marcar_rejeitada(
                session, emissao, "CONSULTA_NFE",
                f"nao foi possivel confirmar na SEFAZ se a NF-e {emissao.chave_acesso} "
                f"ja foi autorizada: {exc}",
            )
            return True
        if eh_autorizado(previa.c_stat) or eh_denegado(previa.c_stat):
            # Resultado final ja registrado na SEFAZ para esta chave: usa a
            # consulta como resposta, sem remontar nem reenviar. Denegacao
            # cai no ramo terminal la embaixo (grava protocolo, sem retry).
            resposta = previa
        elif not nao_encontrada(previa.c_stat):
            # So 217 ("nao consta na base") garante que reenviar e seguro.
            # Qualquer outra resposta (erro da SEFAZ, cStat que nao parseou
            # -> None, codigo desconhecido) = estado real desconhecido:
            # reenviar arriscaria duplicidade ou sobrescrever o xml_nfe com
            # um XML diferente do que a SEFAZ tem. Nao chuta -- agenda nova
            # consulta pelo backoff normal.
            await _marcar_rejeitada(
                session, emissao, "CONSULTA_INCONCLUSIVA",
                f"a consulta da NF-e {emissao.chave_acesso} na SEFAZ nao confirmou "
                f"autorizacao nem inexistencia (cStat {previa.c_stat}: {previa.x_motivo}); "
                "reenvio suspenso ate nova consulta",
            )
            return True
        # else: 217 -> SEFAZ nao tem a chave; segue para remontar e enviar.

    if resposta is None:
        try:
            chave, assinado = await _montar_e_assinar_nfe(session, emissao, empresa, ambiente_emissao, settings)
        except (CertificateError, InvalidToken, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Tudo aqui e montagem PURA desta linha (nada desta tentativa foi
            # enviado a SEFAZ; se havia tentativa anterior, a consulta acima
            # ja confirmou que a chave nao consta na SEFAZ -- 217), entao recusar a linha e
            # sempre seguro. Alem do trio da NFS-e (certificado / FERNET_KEY /
            # ValueError de validacao, que inclui AliquotaInterestadualInvalida),
            # cobre TypeError/AttributeError/KeyError de cadastro incompleto
            # (ex.: Cliente.uf ou Empresa.uf nulos -> None.strip() no calculo
            # de ICMS). Sem isso, a excecao escapa pro loop_worker, a linha
            # volta a pendente no rollback e, sendo a mais antiga, e
            # repescada a cada volta pra sempre -- travando a fila de NF-e de
            # todas as empresas atras dela.
            detalhe = str(exc) or (
                "certificado cifrado desta empresa nao pode ser decifrado com a "
                "FERNET_KEY atual (recadastre o certificado)"
            )
            await _marcar_rejeitada(session, emissao, "CERTIFICADO_OU_DADOS", detalhe)
            return True

        if ja_submetida and chave != emissao.chave_acesso:
            # Nunca deveria acontecer: a chave so depende de criado_em, CNPJ,
            # UF, serie e numero, que nao mudam depois da criacao da linha.
            # Se mudou, enviar criaria uma NF-e com OUTRA chave pra mesma
            # serie/numero enquanto a gravada pode estar em processamento --
            # bloqueia e deixa para analise manual.
            logger.error(
                "emissao NF-e %s: chave recalculada %s diverge da gravada %s; envio bloqueado",
                emissao.id, chave, emissao.chave_acesso,
            )
            await _marcar_rejeitada(
                session, emissao, "CHAVE_DIVERGENTE",
                f"chave recalculada {chave} diverge da chave ja gravada {emissao.chave_acesso} "
                "(CNPJ/UF/serie/numero/criado_em mudaram?); envio bloqueado",
            )
            return True

        # Chave e XML gravados ANTES do envio, de proposito: se o processo
        # morrer entre o envio e o commit final, a proxima tentativa ja sabe
        # a chave (consulta em vez de reenviar as cegas) e o xml_nfe e
        # exatamente o que foi enviado. O ambiente vai no MESMO commit: chave,
        # XML (com seu tpAmb) e o ambiente para onde foram enviados formam um
        # snapshot unico -- ou tudo, ou nada. Numa retentativa (217) o valor
        # ja e o gravado; reatribuir e no-op, nunca troca de ambiente.
        emissao.chave_acesso = chave
        emissao.xml_nfe = assinado
        emissao.ambiente = ambiente_emissao
        await session.commit()
        # O commit acima solta a trava do SELECT ... FOR UPDATE; readquire
        # para o resto do processamento continuar exclusivo desta linha.
        await session.execute(select(EmissaoNfe).where(EmissaoNfe.id == emissao.id).with_for_update())

        try:
            resposta = await cliente_sefaz.autorizar(assinado, empresa.uf, ambiente)
        except Exception as exc:
            await _marcar_rejeitada(session, emissao, "TRANSPORTE", str(exc))
            return True

    emissao.resposta_bruta = str(resposta.bruta)
    if eh_autorizado(resposta.c_stat):
        emissao.status = StatusEmissao.autorizada
        emissao.protocolo_autorizacao = resposta.protocolo
        # Limpa erro/agendamento de uma tentativa rejeitada anterior.
        emissao.erros = None
        emissao.proxima_tentativa_em = None
    else:
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = json.dumps(
            [{"codigo": resposta.c_stat or "SEFAZ", "titulo": resposta.x_motivo or "NF-e rejeitada pela SEFAZ"}],
            ensure_ascii=False,
        )
        if eh_denegado(resposta.c_stat):
            # Uso denegado e FINAL: o numero fica queimado na SEFAZ e o
            # protocolo da denegacao e prova que precisa ser guardada.
            # Retentar so repetiria a mesma denegacao -- sem agendamento,
            # o promotor de reemissao automatica nunca repesca a linha.
            emissao.protocolo_autorizacao = resposta.protocolo
            emissao.proxima_tentativa_em = None
            logger.warning("emissao NF-e %s com uso denegado; resposta bruta: %s", emissao.id, resposta.bruta)
        else:
            logger.warning("emissao NF-e %s rejeitada; resposta bruta: %s", emissao.id, resposta.bruta)
            _agendar_proxima_tentativa(emissao)

    await session.commit()
    return True


async def processar_reemissao_automatica_pendente_nfe(session: AsyncSession) -> bool:
    """Espelha processar_reemissao_automatica_pendente para NF-e: promove UMA
    emissao rejeitada com tentativa automatica vencida de volta pra
    "pendente" (estado inicial da NF-e). processar_uma_pendente_nfe
    cuida do reenvio -- consultando a SEFAZ antes, ja que a linha tem chave."""
    agora = datetime.now(timezone.utc)
    stmt = (
        select(EmissaoNfe)
        .where(
            EmissaoNfe.status == StatusEmissao.rejeitada,
            EmissaoNfe.proxima_tentativa_em.isnot(None),
            EmissaoNfe.proxima_tentativa_em <= agora,
        )
        .order_by(EmissaoNfe.proxima_tentativa_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    emissao = (await session.execute(stmt)).scalar_one_or_none()
    if emissao is None:
        return False

    emissao.status = StatusEmissao.pendente
    emissao.proxima_tentativa_em = None
    await session.commit()
    return True


async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_reemissao_automatica = await processar_reemissao_automatica_pendente(session)
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
            async with session_factory() as session:
                processou_confirmacao_spedy = await processar_uma_aguardando_confirmacao_spedy(session)
            async with session_factory() as session:
                processou_confirmacao_cancel_spedy = await processar_um_cancelamento_aguardando_confirmacao_spedy(session)
            async with session_factory() as session:
                processou_reemissao_automatica_nfe = await processar_reemissao_automatica_pendente_nfe(session)
            async with session_factory() as session:
                processou_emissao_nfe = await processar_uma_pendente_nfe(session)
        except Exception:
            # Supervisao do loop, de proposito abrangente: o tratamento fino
            # (por tipo de erro, por linha) mora dentro de
            # processar_uma_pendente/processar_um_cancelamento_pendente. Aqui
            # o unico objetivo e garantir que NENHUMA excecao inesperada —
            # banco reiniciado, conexao derrubada, bug novo — mate o processo
            # e pare a emissao/cancelamento de todas as empresas.
            logger.exception("falha inesperada ao processar fila pendente; o loop continua")
            processou_reemissao_automatica = False
            processou_emissao = False
            processou_cancelamento = False
            processou_confirmacao_spedy = False
            processou_confirmacao_cancel_spedy = False
            processou_reemissao_automatica_nfe = False
            processou_emissao_nfe = False
        processou_algo = any([
            processou_reemissao_automatica, processou_emissao, processou_cancelamento,
            processou_confirmacao_spedy, processou_confirmacao_cancel_spedy,
            processou_reemissao_automatica_nfe, processou_emissao_nfe,
        ])
        if not processou_algo:
            await asyncio.sleep(intervalo_segundos)
        elif processou_emissao or processou_emissao_nfe:
            # So pausa apos emissao de verdade (nao apos so promover uma
            # reemissao automatica de rejeitada->pendente, que nao fala com
            # SEFIN/Spedy) -- evita rajada contra o provedor num backlog
            # grande, sem atrasar artificialmente o resto do loop.
            await asyncio.sleep(PACING_SEGUNDOS)
