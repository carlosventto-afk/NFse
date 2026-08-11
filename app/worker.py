import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.models import AmbienteEnum, Emissao, Empresa, StatusEmissao
from nfse_core import (
    CertificateError,
    SefinClient,
    SefinError,
    build_dps_xml,
    ler_resposta_emissao,
    sign_dps,
)


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
    pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
    senha = decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) if empresa.certificado_senha_cifrada else None

    dados = DadosEmissao(
        tomador_cpf_cnpj=emissao.tomador_cpf_cnpj,
        tomador_nome=emissao.tomador_nome,
        tomador_email=emissao.tomador_email,
        descricao=emissao.descricao,
        valor=emissao.valor,
        competencia=emissao.competencia,
    )
    dps_data = montar_dps_data(empresa, emissao.serie, emissao.numero, dados)

    try:
        xml = build_dps_xml(dps_data)
        assinado = sign_dps(xml, pfx_base64, senha)
        emissao.xml_dps = assinado

        # AmbienteEnum(...) normaliza tanto o enum quanto o str puro que o
        # SQLAlchemy devolve apos um session.get() (coluna e String, nao um
        # Enum do SQLAlchemy — .value direto em cima do valor recem-carregado
        # do banco quebra com AttributeError; ver Task 5).
        cliente = SefinClient(AmbienteEnum(empresa.ambiente).value, pfx_base64, senha)
        try:
            bruta = await cliente.emitir_dps(assinado)
        finally:
            await cliente.close()
    except SefinError as exc:
        # Falha de transporte/infra: SEFIN fora do ar, timeout, DNS, resposta
        # nao-JSON. So esta linha falha — a fila continua para as outras.
        await _marcar_rejeitada(session, emissao, "TRANSPORTE", str(exc))
        return True
    except (CertificateError, ValueError) as exc:
        # CertificateError (PFX invalido/senha errada/certificado vencido —
        # nfse_core/signer.py, ex.: certificado expirado apos 1 ano, evento
        # esperado) e ValueError (build_dps_xml recusando dados da propria
        # linha: CNPJ do prestador ausente, IBGE invalido, valor <= 0, doc do
        # tomador mal formado) sao ambos problemas ISOLADOS desta emissao/
        # empresa, nao da infraestrutura. Sem este except, qualquer um deles
        # escapa de processar_uma_pendente, atravessa o `while True` de
        # loop_worker sem tratamento e derruba o processo do worker inteiro
        # — parando a emissao de TODAS as empresas que compartilham o worker,
        # nao so a que tem o certificado vencido ou o CNPJ mal cadastrado.
        # CertificateError ja e subclasse de ValueError; agrupar os dois no
        # mesmo except evita duplicar o tratamento sem alargar o escopo real
        # (ambos sao "recuse esta linha", nunca "derrube o processo").
        await _marcar_rejeitada(session, emissao, "CERTIFICADO_OU_DADOS", str(exc))
        return True

    resultado = ler_resposta_emissao(bruta)
    if resultado.autorizada:
        emissao.status = StatusEmissao.autorizada
        emissao.chave_acesso = resultado.chave_acesso
        emissao.xml_nfse = resultado.xml_nfse
        emissao.dps_id = dps_data.dps_id
    else:
        emissao.status = StatusEmissao.rejeitada
        emissao.erros = resultado.erros_json()

    await session.commit()
    return True


async def loop_worker(session_factory: async_sessionmaker, intervalo_segundos: float = 5.0) -> None:
    while True:
        async with session_factory() as session:
            processou = await processar_uma_pendente(session)
        if not processou:
            await asyncio.sleep(intervalo_segundos)
