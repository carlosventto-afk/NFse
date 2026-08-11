import base64
import gzip
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.crypto import cifrar
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao
from nfse_core import CertificateError, SefinError
import app.worker as worker


async def _empresa_e_emissao_pendente(db_session, tomador_cpf_cnpj: str | None = "98765432100") -> Emissao:
    fernet_key = get_settings().fernet_key
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, tomador_cpf_cnpj=tomador_cpf_cnpj, tomador_nome="Cliente",
        descricao="Lavagem de roupa", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


def _cliente_falso_autorizado():
    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            return {
                "_http_status": 201,
                "chaveAcesso": "1" * 50,
                "nfseXmlGZipB64": base64.b64encode(
                    gzip.compress(b"<NFSe>autorizada</NFSe>")
                ).decode(),
            }

        async def close(self) -> None:
            pass

    return ClienteFalso


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_autorizada_em_sucesso(db_session, monkeypatch):
    emissao = await _empresa_e_emissao_pendente(db_session)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "1" * 50
    assert emissao.xml_nfse == b"<NFSe>autorizada</NFSe>"


@pytest.mark.asyncio
async def test_processar_uma_pendente_autoriza_mesmo_sem_documento_do_tomador(db_session, monkeypatch):
    """Cobre o caso do webhook Stone: emissao sem CPF/CNPJ do tomador (Task 7
    tornou isso opcional em build_dps_xml) precisa passar pelo worker sem
    levantar excecao."""
    emissao = await _empresa_e_emissao_pendente(db_session, tomador_cpf_cnpj=None)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_rejeitada_com_erros(db_session, monkeypatch):
    emissao = await _empresa_e_emissao_pendente(db_session)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            return {"_http_status": 422, "erros": [{"codigo": "E0714", "mensagem": "Erro na assinatura"}]}

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.erros is not None
    assert "E0714" in emissao.erros


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_rejeitada_em_falha_de_transporte(db_session, monkeypatch):
    """SEFIN fora do ar / timeout / DNS: SefinError precisa ser tratada por
    linha, sem propagar para fora de processar_uma_pendente (o que derrubaria
    o processo do worker inteiro dentro do while True de loop_worker)."""
    emissao = await _empresa_e_emissao_pendente(db_session)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            # Mensagem com aspas e barra invertida: reproduz o formato de erro
            # de TLS/rede real e cobre o escaping via json.dumps (em vez de
            # f-string manual, que quebraria o JSON aqui).
            raise SefinError('falha de rede com a SEFIN (ConnectTimeout): [SSL: "C:\\cert.pem"] timeout')

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.erros is not None
    erros = json.loads(emissao.erros)  # precisa ser JSON valido apesar das aspas/barras na mensagem
    assert erros[0]["codigo"] == "TRANSPORTE"
    assert "ConnectTimeout" in erros[0]["titulo"]


@pytest.mark.asyncio
async def test_processar_uma_pendente_marca_rejeitada_quando_certificado_invalido(db_session, monkeypatch):
    """Certificado A1 vencido/senha errada (CertificateError, levantada por
    nfse_core.signer ao assinar) e um problema isolado desta empresa, nao da
    infraestrutura: nao pode propagar e derrubar o worker inteiro."""
    emissao = await _empresa_e_emissao_pendente(db_session)

    def _sign_dps_com_certificado_vencido(xml, pfx, senha):
        raise CertificateError("Certificado A1 inválido ou senha incorreta: vencido")

    monkeypatch.setattr(worker, "sign_dps", _sign_dps_com_certificado_vencido)
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    assert emissao.erros is not None
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "CERTIFICADO_OU_DADOS"
    assert "vencido" in erros[0]["titulo"]


@pytest.mark.asyncio
async def test_processar_uma_pendente_devolve_falso_quando_fila_vazia(db_session):
    processou = await worker.processar_uma_pendente(db_session)
    assert processou is False
