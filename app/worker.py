import asyncio
import json
import logging
from datetime import datetime, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.models import AmbienteEnum, Emissao, Empresa, StatusEmissao
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
        # Log da resposta crua: o catalogo de erros so conhece os nomes de
        # campo da SEFIN Nacional. Endpoints proprios de municipio (ex.:
        # Belem) podem usar chaves diferentes pra codigo/descricao, e sem
        # isso a mensagem chega vazia na tela sem pista de por que.
        logger.warning("emissao %s rejeitada; resposta bruta: %s", emissao.id, bruta)

    await session.commit()
    return True


async def _marcar_erro_cancelamento(session: AsyncSession, emissao: Emissao, codigo: str, titulo: str) -> None:
    emissao.status = StatusEmissao.erro_cancelamento
    emissao.erros = json.dumps([{"codigo": codigo, "titulo": titulo}], ensure_ascii=False)
    await session.commit()


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


async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        try:
            async with session_factory() as session:
                processou_emissao = await processar_uma_pendente(session)
            async with session_factory() as session:
                processou_cancelamento = await processar_um_cancelamento_pendente(session)
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
        if not processou_emissao and not processou_cancelamento:
            await asyncio.sleep(intervalo_segundos)
