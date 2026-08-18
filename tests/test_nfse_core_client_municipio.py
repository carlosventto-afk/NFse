import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from nfse_core.client import SefinClient


def _pfx_teste_base64() -> str:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA TESTE LTDA:12345678000199")])
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b"teste", key=chave, cert=certificado, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"senha123"),
    )
    return base64.b64encode(pfx_bytes).decode()


class _RespostaFalsa:
    def __init__(self, corpo: dict):
        self.status_code = 201
        self._corpo = corpo

    def json(self) -> dict:
        return self._corpo


async def _emitir_e_capturar_url(cliente: SefinClient) -> str:
    chamadas: list[tuple[str, str]] = []

    async def _request_falso(method: str, url: str, **kwargs) -> _RespostaFalsa:
        chamadas.append((method, url))
        return _RespostaFalsa({"chaveAcesso": "abc"})

    cliente._request = _request_falso  # type: ignore[method-assign]
    try:
        await cliente.emitir_dps(b"<DPS/>")
    finally:
        await cliente.close()
    assert len(chamadas) == 1
    return chamadas[0][1]


@pytest.mark.asyncio
async def test_emitir_dps_usa_endpoint_proprio_de_belem_em_homologacao():
    cliente = SefinClient(
        "homologacao", _pfx_teste_base64(), "senha123", municipio_ibge="1501402",
    )
    url = await _emitir_e_capturar_url(cliente)
    assert url == "https://homol-nfse2.belem.pa.gov.br/notafiscal-adn-ws/api/adn/dps"


@pytest.mark.asyncio
async def test_emitir_dps_sem_municipio_usa_endpoint_nacional():
    cliente = SefinClient("homologacao", _pfx_teste_base64(), "senha123")
    url = await _emitir_e_capturar_url(cliente)
    assert url == "/nfse"


@pytest.mark.asyncio
async def test_emitir_dps_municipio_sem_url_de_producao_cai_no_nacional():
    # Belem so tem homologacao mapeada -- producao (nao publicada no manual)
    # precisa cair de volta pro endpoint nacional, nao quebrar.
    cliente = SefinClient(
        "producao", _pfx_teste_base64(), "senha123", municipio_ibge="1501402",
    )
    url = await _emitir_e_capturar_url(cliente)
    assert url == "/nfse"


@pytest.mark.asyncio
async def test_emitir_dps_municipio_desconhecido_cai_no_nacional():
    cliente = SefinClient(
        "homologacao", _pfx_teste_base64(), "senha123", municipio_ibge="9999999",
    )
    url = await _emitir_e_capturar_url(cliente)
    assert url == "/nfse"
