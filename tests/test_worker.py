import asyncio
import base64
import gzip
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.crypto import cifrar, hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario
from nfse_core import CertificateError, SefinError
import app.worker as worker


async def _empresa_e_emissao_pendente(
    db_session,
    tomador_cpf_cnpj: str | None = "98765432100",
    fernet_key: str | None = None,
    dps_id: str | None = None,
) -> Emissao:
    """Cria empresa + emissao pendente.

    `fernet_key` permite cifrar o certificado com uma chave DIFERENTE da do
    ambiente, reproduzindo o cenario de `decifrar()` levantando InvalidToken.
    `dps_id` reproduz uma tentativa anterior que submeteu a DPS e morreu antes
    de gravar o resultado.
    """
    fernet_key = fernet_key or get_settings().fernet_key
    titular = Usuario(email=f"titular-worker-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado=cifrar("pfx-fake-base64", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, dps_id=dps_id,
        tomador_cpf_cnpj=tomador_cpf_cnpj, tomador_nome="Cliente",
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


@pytest.mark.asyncio
async def test_processar_uma_pendente_rejeita_quando_certificado_nao_decifra(db_session, monkeypatch):
    """FERNET_KEY rotacionada / linha cifrada com outra chave: `decifrar`
    levanta `cryptography.fernet.InvalidToken`, que NAO e subclasse de
    ValueError. Sem tratamento explicito, ela escapa de
    processar_uma_pendente, atravessa o `while True` de loop_worker e derruba
    o worker inteiro — parando a emissao de TODAS as empresas por causa do
    certificado mal cifrado de UMA.
    """
    outra_chave = Fernet.generate_key().decode()
    emissao = await _empresa_e_emissao_pendente(db_session, fernet_key=outra_chave)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    monkeypatch.setattr(worker, "SefinClient", _cliente_falso_autorizado())

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "CERTIFICADO_OU_DADOS"
    assert erros[0]["titulo"]  # InvalidToken vem sem mensagem — nao pode gravar vazio


@pytest.mark.asyncio
async def test_processar_uma_pendente_grava_dps_id_antes_de_chamar_a_sefin(db_session, monkeypatch):
    """Se o processo morrer entre a resposta da SEFIN e o commit, o dps_id
    precisa ja estar no banco — senao a proxima tentativa reenvia a DPS as
    cegas e uma nota autorizada acaba registrada como rejeitada."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    emissao = await _empresa_e_emissao_pendente(db_session)
    dps_id_visto: list[str | None] = []

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")

    # Engine/sessao SEPARADA: enxerga apenas o que ja foi commitado, e nao a
    # transacao aberta do worker.
    outro_engine = create_async_engine(get_settings().database_url_test)
    outra_fabrica = async_sessionmaker(outro_engine, expire_on_commit=False)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            async with outra_fabrica() as outra:
                linha = (
                    await outra.execute(select(Emissao).where(Emissao.id == emissao.id))
                ).scalar_one()
                dps_id_visto.append(linha.dps_id)
            return {
                "_http_status": 201, "chaveAcesso": "1" * 50,
                "nfseXmlGZipB64": base64.b64encode(gzip.compress(b"<NFSe>ok</NFSe>")).decode(),
            }

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    try:
        assert await worker.processar_uma_pendente(db_session) is True
    finally:
        await outro_engine.dispose()

    assert dps_id_visto and dps_id_visto[0] is not None
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.dps_id == dps_id_visto[0]


@pytest.mark.asyncio
async def test_processar_uma_pendente_consulta_dps_ja_submetida_em_vez_de_reenviar(db_session, monkeypatch):
    """Linha pendente que JA tem dps_id = tentativa anterior submeteu e morreu.
    Reenviar as cegas faz a SEFIN rejeitar por DPS duplicada (E0202) e grava
    como rejeitada uma nota que foi autorizada — ver ARMADILHAS.md item 12."""
    emissao = await _empresa_e_emissao_pendente(db_session, dps_id="DPS" + "9" * 42)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    chamadas = {"consultar": 0, "emitir": 0}

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_dps(self, dps_id: str) -> dict:
            chamadas["consultar"] += 1
            return {
                "_http_status": 200, "chaveAcesso": "7" * 50,
                "nfseXmlGZipB64": base64.b64encode(gzip.compress(b"<NFSe>ja autorizada</NFSe>")).decode(),
            }

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            chamadas["emitir"] += 1
            return {"_http_status": 422, "erros": [{"codigo": "E0202", "mensagem": "DPS duplicada"}]}

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    assert await worker.processar_uma_pendente(db_session) is True

    assert chamadas == {"consultar": 1, "emitir": 0}
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "7" * 50
    assert emissao.xml_nfse == b"<NFSe>ja autorizada</NFSe>"


@pytest.mark.asyncio
async def test_processar_uma_pendente_reenvia_quando_sefin_nao_conhece_a_dps(db_session, monkeypatch):
    """Consulta devolve 404 (a DPS nunca chegou a ser registrada): reenviar e
    o caminho certo, senao a emissao ficaria travada para sempre."""
    emissao = await _empresa_e_emissao_pendente(db_session, dps_id="DPS" + "8" * 42)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    chamadas = {"consultar": 0, "emitir": 0}

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_dps(self, dps_id: str) -> dict:
            chamadas["consultar"] += 1
            return {"_http_status": 404, "erros": [{"codigo": "E0000", "mensagem": "DPS nao encontrada"}]}

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            chamadas["emitir"] += 1
            return {
                "_http_status": 201, "chaveAcesso": "5" * 50,
                "nfseXmlGZipB64": base64.b64encode(gzip.compress(b"<NFSe>nova</NFSe>")).decode(),
            }

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    assert await worker.processar_uma_pendente(db_session) is True

    assert chamadas == {"consultar": 1, "emitir": 1}
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "5" * 50


@pytest.mark.asyncio
async def test_processar_uma_pendente_nao_reenvia_as_cegas_quando_a_consulta_falha(db_session, monkeypatch):
    """SEFIN fora do ar durante a consulta: nao da para saber se a DPS virou
    nota. ARMADILHAS.md item 12: nao reenvie as cegas. Fica registrado com um
    codigo proprio para reconciliacao manual."""
    emissao = await _empresa_e_emissao_pendente(db_session, dps_id="DPS" + "7" * 42)

    monkeypatch.setattr(worker, "sign_dps", lambda xml, pfx, senha: b"<DPS assinada/>")
    chamadas = {"emitir": 0}

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_dps(self, dps_id: str) -> dict:
            raise SefinError("SEFIN indisponivel (HTTP 503)")

        async def emitir_dps(self, xml_assinado: bytes) -> dict:
            chamadas["emitir"] += 1
            return {"_http_status": 201, "chaveAcesso": "1" * 50}

        async def close(self) -> None:
            pass

    monkeypatch.setattr(worker, "SefinClient", ClienteFalso)

    assert await worker.processar_uma_pendente(db_session) is True

    assert chamadas["emitir"] == 0
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "CONSULTA_DPS"


@pytest.mark.asyncio
async def test_loop_worker_sobrevive_a_excecao_inesperada(monkeypatch, caplog):
    """Uma excecao inesperada (banco caiu, driver estourou) nao pode derrubar
    o processo do worker: o loop e o ponto de supervisao, loga e continua."""
    chamadas: list[int] = []

    async def _processar_explodindo(session, settings=None):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("conexao com o banco caiu no meio do processamento")
        raise asyncio.CancelledError  # so para o teste sair do while True

    class _FabricaFalsa:
        def __call__(self):
            return self

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(worker, "processar_uma_pendente", _processar_explodindo)

    with pytest.raises(asyncio.CancelledError):
        await worker.loop_worker(_FabricaFalsa(), intervalo_segundos=0)

    assert len(chamadas) == 2  # continuou depois da excecao da primeira volta
    assert any("inesperada" in registro.message for registro in caplog.records)
