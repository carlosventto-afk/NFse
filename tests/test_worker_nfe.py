import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

import app.worker as worker
from app.config import get_settings
from app.crypto import cifrar, hash_senha
from app.models import (
    AmbienteEnum, Cliente, EmissaoNfe, Empresa, ItemEmissaoNfe, Produto, StatusEmissao, Usuario,
)
from app.worker import processar_reemissao_automatica_pendente_nfe, processar_uma_pendente_nfe
from nfe_core import NFE_NS, RespostaAutorizacao, RespostaConsulta
from nfse_core.signer import DS_NS
from tests.test_nfse_core_signer import _pfx_teste_base64

_PFX = _pfx_teste_base64()


async def _criar_emissao_nfe_pendente(
    db_session,
    *,
    serie: str = "1",
    numero: int = 1,
    status: StatusEmissao = StatusEmissao.aguardando_emissao,
    protocolo_autorizacao: str | None = None,
    chave_acesso: str | None = None,
    xml_nfe: bytes | None = None,
    cliente_uf: str | None = "PA",
    aliquota_interna_destino: Decimal | None = None,
    fernet_key: str | None = None,
    tentativas_reemissao: int = 0,
) -> EmissaoNfe:
    fernet_key = fernet_key or get_settings().fernet_key
    titular = Usuario(email=f"titular-nfe-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=1,
        codigo_tributacao="141001", descricao_servico_padrao="Venda",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar(_PFX, fernet_key),
        certificado_senha_cifrada=cifrar("senha123", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc) + timedelta(days=365),
        webhook_token_hash="x", titular_id=titular.id,
        inscricao_estadual="123456789", crt=1, uf="PA",
    )
    db_session.add(empresa)
    await db_session.flush()
    cliente = Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Cliente Teste", uf=cliente_uf)
    produto = Produto(
        empresa_id=empresa.id, codigo_interno="SKU1", descricao="Camiseta", ncm="61091000",
        cfop_padrao="5102", unidade="UN", csosn_icms="102", valor_unitario_padrao=Decimal("10.00"),
    )
    db_session.add_all([cliente, produto])
    await db_session.flush()
    emissao = EmissaoNfe(
        empresa_id=empresa.id, cliente_id=cliente.id, serie=serie, numero=numero, status=status,
        protocolo_autorizacao=protocolo_autorizacao, chave_acesso=chave_acesso, xml_nfe=xml_nfe,
        tentativas_reemissao=tentativas_reemissao,
    )
    db_session.add(emissao)
    await db_session.flush()
    db_session.add(ItemEmissaoNfe(
        emissao_nfe_id=emissao.id, produto_id=produto.id, quantidade=Decimal("2"),
        valor_unitario=Decimal("49.90"), valor_total=Decimal("99.80"), cfop="5102",
        aliquota_interna_destino=aliquota_interna_destino,
    ))
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


def _resposta_autorizada(protocolo: str = "115260000000001") -> RespostaAutorizacao:
    return RespostaAutorizacao(
        autorizada=True, c_stat="100", x_motivo="Autorizado o uso da NF-e", protocolo=protocolo,
        bruta={"cStat": "100"},
    )


def _resposta_rejeitada(c_stat: str) -> RespostaAutorizacao:
    return RespostaAutorizacao(
        autorizada=False, c_stat=c_stat, x_motivo="Uso denegado", protocolo=None, bruta={"cStat": c_stat},
    )


def _consulta(autorizada: bool, c_stat: str, protocolo: str | None = None) -> RespostaConsulta:
    return RespostaConsulta(
        autorizada=autorizada, c_stat=c_stat, x_motivo="x", protocolo=protocolo, bruta={"cStat": c_stat},
    )


# --- casos do brief ---------------------------------------------------------


@patch("app.worker.SefazClient")
async def test_grava_chave_de_acesso_antes_de_chamar_sefaz(mock_client_cls, db_session):
    emissao = await _criar_emissao_nfe_pendente(db_session)
    engine = create_async_engine(get_settings().database_url_test)
    visto_pela_outra_conexao: dict = {}

    async def _autorizar_explodindo(xml_assinado, uf, ambiente):
        # O que OUTRA conexao enxerga no momento do envio: a chave e o XML
        # assinado ja precisam estar commitados (se o processo morrer aqui, a
        # proxima tentativa sabe o que foi enviado).
        async with engine.connect() as conn:
            linha = (await conn.execute(
                select(EmissaoNfe.chave_acesso, EmissaoNfe.xml_nfe).where(EmissaoNfe.id == emissao.id)
            )).one()
        visto_pela_outra_conexao.update(chave=linha.chave_acesso, xml=linha.xml_nfe, enviado=xml_assinado)
        raise Exception("rede caiu")

    mock_client_cls.return_value.autorizar = AsyncMock(side_effect=_autorizar_explodindo)
    try:
        # Excecao de transporte NAO escapa (derrubaria o loop_worker):
        # vira rejeicao desta linha so.
        assert await processar_uma_pendente_nfe(db_session, get_settings()) is True
    finally:
        await engine.dispose()

    await db_session.refresh(emissao)
    assert emissao.chave_acesso is not None and len(emissao.chave_acesso) == 44
    assert visto_pela_outra_conexao["chave"] == emissao.chave_acesso
    assert visto_pela_outra_conexao["xml"] == visto_pela_outra_conexao["enviado"] == emissao.xml_nfe
    assert emissao.status == StatusEmissao.rejeitada
    assert json.loads(emissao.erros)[0]["codigo"] == "TRANSPORTE"
    assert emissao.tentativas_reemissao == 1
    assert emissao.proxima_tentativa_em is not None


@patch("app.worker.SefazClient")
async def test_nao_reenvia_quando_ja_tem_protocolo_de_autorizacao(mock_client_cls, db_session):
    await _criar_emissao_nfe_pendente(db_session, protocolo_autorizacao="123", status=StatusEmissao.autorizada)
    processou = await processar_uma_pendente_nfe(db_session, get_settings())
    assert processou is False
    mock_client_cls.return_value.autorizar.assert_not_called()


@patch("app.worker.SefazClient")
async def test_rejeicao_mantem_mesma_serie_numero_pra_reenvio(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_rejeitada("110"))
    emissao = await _criar_emissao_nfe_pendente(db_session, serie="1", numero=42)
    antes = datetime.now(timezone.utc)
    await processar_uma_pendente_nfe(db_session, get_settings())
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.serie == "1" and emissao.numero == 42
    assert json.loads(emissao.erros) == [{"codigo": "110", "titulo": "Uso denegado"}]
    assert emissao.resposta_bruta is not None
    # Mesmo backoff da NFS-e: 1a rejeicao agenda reenvio em ~2 min.
    assert emissao.tentativas_reemissao == 1
    assert antes + timedelta(minutes=2) <= emissao.proxima_tentativa_em <= datetime.now(timezone.utc) + timedelta(minutes=2)


# --- caminho feliz ----------------------------------------------------------


@patch("app.worker.SefazClient")
async def test_autoriza_e_grava_protocolo_e_xml_assinado(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_autorizada("999"))
    mock_client_cls.return_value.consultar_protocolo = AsyncMock()
    emissao = await _criar_emissao_nfe_pendente(db_session, numero=7)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.protocolo_autorizacao == "999"
    assert emissao.erros is None
    assert emissao.resposta_bruta is not None
    # Primeira tentativa: nada foi enviado antes, nao consulta.
    mock_client_cls.return_value.consultar_protocolo.assert_not_called()
    xml_enviado, uf, ambiente = mock_client_cls.return_value.autorizar.call_args.args
    assert xml_enviado == emissao.xml_nfe
    assert uf == "PA"
    assert ambiente.value == "homologacao"
    root = etree.fromstring(emissao.xml_nfe)
    inf = root.find(f"{{{NFE_NS}}}infNFe")
    assert inf.get("Id") == f"NFe{emissao.chave_acesso}"
    assert root.find(f"{{{DS_NS}}}Signature") is not None


# --- idempotencia em retentativa --------------------------------------------


_CHAVE_ANTERIOR = "15261012345678000199550010000000071000000079"  # aamm de outro mes de proposito
_XML_ANTERIOR = b'<?xml version="1.0"?><NFe>assinada-na-tentativa-anterior</NFe>'


@patch("app.worker.SefazClient")
async def test_retentativa_consulta_antes_e_nao_reenvia_se_ja_autorizada(mock_client_cls, db_session, monkeypatch):
    mock_client_cls.return_value.consultar_protocolo = AsyncMock(return_value=_consulta(True, "100", "555"))
    mock_client_cls.return_value.autorizar = AsyncMock()
    monkeypatch.setattr(worker, "montar_nfe_data", _nao_deveria_recalcular)
    emissao = await _criar_emissao_nfe_pendente(db_session, chave_acesso=_CHAVE_ANTERIOR, xml_nfe=_XML_ANTERIOR)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_not_called()
    chave, uf, _amb = mock_client_cls.return_value.consultar_protocolo.call_args.args
    assert (chave, uf) == (_CHAVE_ANTERIOR, "PA")
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.protocolo_autorizacao == "555"
    assert emissao.chave_acesso == _CHAVE_ANTERIOR
    assert emissao.xml_nfe == _XML_ANTERIOR


@patch("app.worker.SefazClient")
async def test_retentativa_reenvia_exatamente_o_xml_persistido_sem_recalcular_chave(
    mock_client_cls, db_session, monkeypatch,
):
    # Mesmo que o mes tenha virado (aamm da chave diferente de hoje), a
    # retentativa reaproveita a chave/XML ja gravados -- nunca recalcula.
    mock_client_cls.return_value.consultar_protocolo = AsyncMock(return_value=_consulta(False, "217"))
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_autorizada("777"))
    monkeypatch.setattr(worker, "montar_nfe_data", _nao_deveria_recalcular)
    emissao = await _criar_emissao_nfe_pendente(db_session, chave_acesso=_CHAVE_ANTERIOR, xml_nfe=_XML_ANTERIOR)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_awaited_once()
    assert mock_client_cls.return_value.autorizar.call_args.args[0] == _XML_ANTERIOR
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == _CHAVE_ANTERIOR
    assert emissao.protocolo_autorizacao == "777"


@patch("app.worker.SefazClient")
async def test_retentativa_com_falha_na_consulta_nao_reenvia(mock_client_cls, db_session):
    mock_client_cls.return_value.consultar_protocolo = AsyncMock(side_effect=Exception("timeout"))
    mock_client_cls.return_value.autorizar = AsyncMock()
    emissao = await _criar_emissao_nfe_pendente(db_session, chave_acesso=_CHAVE_ANTERIOR, xml_nfe=_XML_ANTERIOR)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_not_called()
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert json.loads(emissao.erros)[0]["codigo"] == "CONSULTA_NFE"
    assert emissao.chave_acesso == _CHAVE_ANTERIOR


def _nao_deveria_recalcular(*args, **kwargs):
    raise AssertionError("retentativa nao pode remontar a NF-e (chave tem aamm)")


# --- interestadual (aliquota persistida no item) ----------------------------


@patch("app.worker.SefazClient")
async def test_interestadual_usa_aliquota_interna_destino_gravada_no_item(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_autorizada())
    emissao = await _criar_emissao_nfe_pendente(db_session, cliente_uf="SP", aliquota_interna_destino=Decimal("18"))

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    root = etree.fromstring(emissao.xml_nfe)
    # PA -> SP: interestadual 12%, destino 18% => DIFAL = 99.80 * 6% = 5.99
    assert root.find(f".//{{{NFE_NS}}}vICMSUFDest").text == "5.99"


@patch("app.worker.SefazClient")
async def test_interestadual_sem_aliquota_rejeita_a_linha_sem_enviar(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock()
    emissao = await _criar_emissao_nfe_pendente(db_session, cliente_uf="SP", aliquota_interna_destino=None)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_not_called()
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.chave_acesso is None
    erro = json.loads(emissao.erros)[0]
    assert erro["codigo"] == "CERTIFICADO_OU_DADOS"
    assert "aliquota_interna_destino" in erro["titulo"]


# --- erros isolados por linha -----------------------------------------------


@patch("app.worker.SefazClient")
async def test_certificado_cifrado_com_outra_fernet_key_rejeita_sem_derrubar(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock()
    emissao = await _criar_emissao_nfe_pendente(db_session, fernet_key=Fernet.generate_key().decode())

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_not_called()
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert "FERNET_KEY" in json.loads(emissao.erros)[0]["titulo"]


@patch("app.worker.SefazClient")
async def test_cliente_sem_uf_rejeita_sem_derrubar(mock_client_cls, db_session):
    # Cliente.uf e nullable: sem este tratamento um AttributeError escaparia
    # pro loop_worker e a linha ficaria em aguardando_emissao pra sempre,
    # na frente da fila, travando todas as outras NF-e.
    mock_client_cls.return_value.autorizar = AsyncMock()
    emissao = await _criar_emissao_nfe_pendente(db_session, cliente_uf=None)

    assert await processar_uma_pendente_nfe(db_session, get_settings()) is True

    mock_client_cls.return_value.autorizar.assert_not_called()
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada


@patch("app.worker.SefazClient")
async def test_backoff_esgotado_nao_agenda_nova_tentativa(mock_client_cls, db_session):
    mock_client_cls.return_value.autorizar = AsyncMock(return_value=_resposta_rejeitada("225"))
    emissao = await _criar_emissao_nfe_pendente(
        db_session, tentativas_reemissao=worker.MAX_TENTATIVAS_REEMISSAO_AUTOMATICA,
    )

    await processar_uma_pendente_nfe(db_session, get_settings())

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.proxima_tentativa_em is None


# --- promocao de reemissao automatica ---------------------------------------


async def test_reemissao_automatica_promove_rejeitada_vencida_para_aguardando_emissao(db_session):
    emissao = await _criar_emissao_nfe_pendente(db_session, status=StatusEmissao.rejeitada)
    emissao.proxima_tentativa_em = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    assert await processar_reemissao_automatica_pendente_nfe(db_session) is True

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_emissao
    assert emissao.proxima_tentativa_em is None


async def test_reemissao_automatica_ignora_tentativa_ainda_nao_vencida(db_session):
    emissao = await _criar_emissao_nfe_pendente(db_session, status=StatusEmissao.rejeitada)
    emissao.proxima_tentativa_em = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db_session.commit()

    assert await processar_reemissao_automatica_pendente_nfe(db_session) is False

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada


# --- loop_worker ------------------------------------------------------------


async def test_loop_worker_processa_nfe_e_aplica_pacing(monkeypatch):
    chamadas: list[str] = []
    pausas: list[float] = []

    class _FabricaFalsa:
        def __call__(self):
            return self

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    async def _nada(session, settings=None):
        return False

    async def _reemissao_nfe(session):
        chamadas.append("reemissao_nfe")
        return False

    async def _pendente_nfe(session, settings=None):
        chamadas.append("pendente_nfe")
        if chamadas.count("pendente_nfe") > 1:
            raise asyncio.CancelledError  # so pra sair do while True
        return True

    async def _sleep(segundos):
        pausas.append(segundos)

    for nome in (
        "processar_reemissao_automatica_pendente", "processar_uma_pendente",
        "processar_um_cancelamento_pendente", "processar_uma_aguardando_confirmacao_spedy",
        "processar_um_cancelamento_aguardando_confirmacao_spedy",
    ):
        monkeypatch.setattr(worker, nome, _nada)
    monkeypatch.setattr(worker, "processar_reemissao_automatica_pendente_nfe", _reemissao_nfe)
    monkeypatch.setattr(worker, "processar_uma_pendente_nfe", _pendente_nfe)
    monkeypatch.setattr(worker.asyncio, "sleep", _sleep)

    with pytest.raises(asyncio.CancelledError):
        await worker.loop_worker(_FabricaFalsa(), intervalo_segundos=99)

    assert chamadas == ["reemissao_nfe", "pendente_nfe", "reemissao_nfe", "pendente_nfe"]
    assert pausas == [worker.PACING_SEGUNDOS]
