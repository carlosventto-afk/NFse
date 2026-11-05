import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from lxml import etree

from nfse_core.signer import DS_NS, _c14n, sign_root_element


def _pfx_teste_base64(senha: bytes = b"senha123") -> str:
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
        encryption_algorithm=serialization.BestAvailableEncryption(senha),
    )
    return base64.b64encode(pfx_bytes).decode()


def test_sign_root_element_assina_elemento_generico_como_irmao_e_verifica():
    xml = b'<Foo><Bar Id="X1"><Baz>conteudo</Baz></Bar></Foo>'

    assinado = sign_root_element(xml, "Bar", _pfx_teste_base64(), "senha123")

    assert assinado.startswith(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    root = etree.fromstring(assinado)
    signature = root.find(f"{{{DS_NS}}}Signature")
    assert signature is not None
    # Irma do elemento assinado (filha do root), nunca descendente dele.
    assert signature.getparent() is root
    assert root.find("Bar").find(f".//{{{DS_NS}}}Signature") is None
    assert signature.find(f".//{{{DS_NS}}}Reference").get("URI") == "#X1"

    # Digest confere com o c14n do elemento assinado.
    digest_esperado = base64.b64encode(hashlib.sha1(_c14n(root.find("Bar"))).digest()).decode()
    assert signature.find(f".//{{{DS_NS}}}DigestValue").text == digest_esperado

    # SignatureValue verifica com a chave publica do certificado embutido.
    cert_der = base64.b64decode(signature.find(f".//{{{DS_NS}}}X509Certificate").text)
    cert = x509.load_der_x509_certificate(cert_der)
    cert.public_key().verify(
        base64.b64decode(signature.find(f"{{{DS_NS}}}SignatureValue").text),
        _c14n(signature.find(f"{{{DS_NS}}}SignedInfo")),
        padding.PKCS1v15(),
        hashes.SHA1(),
    )


def test_sign_root_element_sem_o_elemento_levanta_value_error():
    import pytest

    with pytest.raises(ValueError, match="nao encontrado"):
        sign_root_element(b"<Foo><Outro Id='X1'/></Foo>", "Bar", _pfx_teste_base64(), "senha123")
