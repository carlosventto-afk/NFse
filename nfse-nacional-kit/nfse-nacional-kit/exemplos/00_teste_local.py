"""Prova que o kit funciona ANTES de você ter certificado ou credencial.

    python exemplos/00_teste_local.py

Gera um certificado autoassinado na memória, monta uma DPS, assina e confere a
assinatura. Não envia nada para a SEFIN e não precisa de internet — serve para
validar que o ambiente Python está correto (lxml, cryptography) e para você ver
o XML que sai daqui.

O certificado gerado aqui NÃO serve para emitir de verdade: a SEFIN só aceita
certificado ICP-Brasil (e-CNPJ/e-CPF A1) emitido por uma AC credenciada.
"""
import base64
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from lxml import etree  # noqa: E402

from nfse_core import DpsData, build_dps_xml, sign_dps  # noqa: E402
from nfse_core.signer import DS_NS, _c14n  # noqa: E402
from nfse_core.dps import NFSE_NS  # noqa: E402

BRT = timezone(timedelta(hours=-3))
SENHA = "teste123"


def certificado_de_teste() -> str:
    """PFX autoassinado em base64 — só para exercitar a assinatura localmente."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "TESTE LOCAL NFSE KIT:00000000000191"),
    ])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome).issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=30))
        .sign(chave, hashes.SHA256())
    )
    pfx = pkcs12.serialize_key_and_certificates(
        b"teste", chave, cert, None,
        serialization.BestAvailableEncryption(SENHA.encode()),
    )
    return base64.b64encode(pfx).decode()


def main() -> None:
    print("1. Gerando certificado de teste...")
    pfx_b64 = certificado_de_teste()

    print("2. Montando a DPS...")
    dados = DpsData(
        tp_amb=2,
        dh_emi=datetime.now(BRT),
        serie="1",
        numero=1,
        competencia=date.today().replace(day=1),
        prest_cnpj="00000000000191",
        prest_im="123456",
        c_loc_emi="1501402",          # Belém/PA
        op_simp_nac=3,
        toma_cpf_cnpj="11144477735",
        toma_nome="Maria da Silva",
        toma_email="maria@exemplo.com.br",
        c_trib_nac="080101",
        x_desc_serv="Mensalidade escolar — turma 5º ano — competência 08/2026",
        v_serv=Decimal("850.00"),
    )
    xml = build_dps_xml(dados)
    print(f"   Id da DPS: {dados.dps_id}  ({len(dados.dps_id)} chars, esperado 45)")
    assert len(dados.dps_id) == 45, "Id da DPS fora do tamanho do leiaute"

    print("3. Assinando...")
    assinado = sign_dps(xml, pfx_b64, SENHA)

    print("4. Conferindo a assinatura (o que a SEFIN faz do lado dela)...")
    root = etree.fromstring(assinado.split(b"?>", 1)[1])
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    sig = root.find(f"{{{DS_NS}}}Signature")
    assert sig is not None, "Signature não foi anexada"

    digest_declarado = sig.find(f".//{{{DS_NS}}}DigestValue").text
    digest_recalculado = base64.b64encode(hashlib.sha1(_c14n(inf)).digest()).decode()
    assert digest_declarado == digest_recalculado, "DigestValue divergente (seria E0714 na SEFIN)"
    print("   [ok] DigestValue confere")

    _key, cert, _chain = pkcs12.load_key_and_certificates(
        base64.b64decode(pfx_b64), SENHA.encode()
    )
    signed_info = sig.find(f"{{{DS_NS}}}SignedInfo")
    cert.public_key().verify(
        base64.b64decode(sig.find(f"{{{DS_NS}}}SignatureValue").text),
        _c14n(signed_info), padding.PKCS1v15(), hashes.SHA1(),
    )
    print("   [ok] SignatureValue confere")

    destino = Path(__file__).resolve().parent.parent / "dps_exemplo_assinada.xml"
    destino.write_bytes(assinado)
    print(f"\n[OK] Tudo certo. XML de exemplo salvo em {destino.name}")
    print("   (assinado com certificado de teste - não serve para emitir de verdade)")


if __name__ == "__main__":
    main()
