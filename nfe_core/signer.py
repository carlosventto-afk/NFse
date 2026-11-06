"""Assinatura da NF-e -- fina camada sobre nfse_core.signer.sign_root_element
(a logica de assinatura XML-DSig e generica, so o elemento assinado muda).
"""
from __future__ import annotations

from nfse_core.signer import CertificateError, sign_root_element

from nfe_core.nfe import NFE_NS

__all__ = ["CertificateError", "sign_nfe"]


def sign_nfe(xml: bytes, pfx_base64: str, password: str | None) -> bytes:
    return sign_root_element(xml, f"{{{NFE_NS}}}infNFe", pfx_base64, password)
