"""Assinatura XMLDSig da DPS com certificado A1 (PFX/PKCS#12, ICP-Brasil).

Assinador MANUAL no padrão DF-e brasileiro (Manual Integrado SNNFSe):
enveloped sobre infDPS (reference "#Id"), RSA-SHA1 + C14N inclusivo,
Signature sem prefixo de namespace (E1228), só o certificado folha no KeyInfo.

Por que manual e não signxml: o signxml calculava o DigestValue sobre uma
forma canônica diferente da serialização final (digest divergente → E0714 na
SEFIN). Aqui o digest é computado por construção sobre a MESMA árvore que é
serializada — verificado byte a byte por scripts/verify_emission.py.

SHA-1 é exigência do padrão DF-e, não escolha nossa.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from nfse_core.dps import NFSE_NS

DS_NS = "http://www.w3.org/2000/09/xmldsig#"


class CertificateError(ValueError):
    """PFX ilegível, senha errada ou certificado sem chave privada."""


def load_pfx(pfx_base64: str, password: str | None):
    """Extrai (chave privada, certificado, cadeia) de um PFX em base64."""
    try:
        raw = base64.b64decode(pfx_base64)
        key, cert, chain = pkcs12.load_key_and_certificates(
            raw, (password or "").encode() or None
        )
    except Exception as exc:
        raise CertificateError(f"Certificado A1 inválido ou senha incorreta: {exc}")
    if key is None or cert is None:
        raise CertificateError("PFX não contém chave privada + certificado")
    return key, cert, list(chain or [])


def load_pfx_pem(pfx_base64: str, password: str | None) -> tuple[bytes, bytes, list[bytes]]:
    """Variante PEM (mTLS do cliente HTTP): (chave PEM, cert PEM, cadeia PEM)."""
    key, cert, chain = load_pfx(pfx_base64, password)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    chain_pem = [c.public_bytes(serialization.Encoding.PEM) for c in chain]
    return key_pem, cert_pem, chain_pem


def _c14n(element: etree._Element) -> bytes:
    """Forma canônica que o validador da SEFIN reproduz.

    MEDIDO em 15/07/2026 (produção restrita, SefinNacional_1.6.0): o digest
    calculado com lxml método "c14n" (C14N 1.0) DIVERGE do recalculado pela
    SEFIN → E0714; com etree.canonicalize (C14N 2.0) a assinatura é aceita.
    A re-serialização standalone do elemento (tostring) também é parte da
    receita: reproduz o contexto que o validador usa.
    """
    return etree.canonicalize(etree.tostring(element).decode()).encode()


def _sign_inner_element(root: etree._Element, inf: etree._Element, key, cert) -> None:
    """Assina `inf` (infDPS ou infEvento) e anexa <Signature> como irmão dele
    em `root`. Receita comum a DPS e evento — ver docstring do módulo."""
    if not inf.get("Id"):
        raise ValueError("Elemento sem atributo Id — nada para assinar")

    # 1. Digest do elemento (c14n inclusivo, com o namespace herdado do root).
    #    O transform enveloped-signature é no-op aqui: a Signature é IRMÃ do
    #    elemento, nunca descendente — o subtree digerido não muda com o append.
    digest_value = base64.b64encode(hashlib.sha1(_c14n(inf)).digest()).decode()
    cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()

    # 2. Bloco Signature compacto (sem whitespace entre tags; ns default = xmldsig)
    signature_xml = (
        f'<Signature xmlns="{DS_NS}">'
        "<SignedInfo>"
        '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        f'<SignatureMethod Algorithm="{DS_NS}rsa-sha1"/>'
        f'<Reference URI="#{inf.get("Id")}">'
        "<Transforms>"
        f'<Transform Algorithm="{DS_NS}enveloped-signature"/>'
        '<Transform Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        "</Transforms>"
        f'<DigestMethod Algorithm="{DS_NS}sha1"/>'
        f"<DigestValue>{digest_value}</DigestValue>"
        "</Reference>"
        "</SignedInfo>"
        "<SignatureValue></SignatureValue>"
        f"<KeyInfo><X509Data><X509Certificate>{cert_b64}</X509Certificate></X509Data></KeyInfo>"
        "</Signature>"
    )
    signature = etree.fromstring(signature_xml.encode())
    root.append(signature)

    # 3. Assina o c14n do SignedInfo JÁ NO CONTEXTO FINAL (herda o ns do pai —
    #    a mesma forma que o validador da SEFIN recalcula)
    signed_info = signature.find(f"{{{DS_NS}}}SignedInfo")
    signature_value = base64.b64encode(
        key.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA1())
    ).decode()
    signature.find(f"{{{DS_NS}}}SignatureValue").text = signature_value


def sign_dps(dps_xml: bytes, pfx_base64: str, password: str | None) -> bytes:
    """Assina a DPS e devolve o XML com <Signature> como último filho de <DPS>."""
    key, cert, _chain = load_pfx(pfx_base64, password)
    root = etree.fromstring(dps_xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    if inf is None:
        raise ValueError("DPS sem infDPS — nada para assinar")
    _sign_inner_element(root, inf, key, cert)

    # Declaração com aspas duplas (manual §6.1.1.a) + standalone, alinhada aos
    # integradores homologados. encoding="unicode" devolve str SEM declaração.
    body = etree.tostring(root, encoding="unicode").encode("utf-8")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + body


def sign_evento(evento_xml: bytes, pfx_base64: str, password: str | None) -> bytes:
    """Assina o Pedido de Registro de Evento (ANEXO II) e devolve o XML com
    <Signature> como último filho de <pedRegEvento>. Mesma receita do
    sign_dps — só muda o elemento assinado (infPedReg, não infEvento: a API
    espera o PEDIDO como raiz, não o evento completo — ver E1235 em evento.py)."""
    key, cert, _chain = load_pfx(pfx_base64, password)
    root = etree.fromstring(evento_xml)
    inf = root.find(f"{{{NFSE_NS}}}infPedReg")
    if inf is None:
        raise ValueError("Pedido de registro de evento sem infPedReg — nada para assinar")
    _sign_inner_element(root, inf, key, cert)

    body = etree.tostring(root, encoding="unicode").encode("utf-8")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + body
