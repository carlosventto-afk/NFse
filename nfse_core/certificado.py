"""Inspeção do certificado A1 — validade, titular e CNPJ.

Serve para o momento do upload (recusar arquivo errado antes de gravar) e para
o alerta de vencimento. Certificado A1 dura 1 ano e a emissão para de funcionar
no dia seguinte ao vencimento, sem aviso nenhum da SEFIN — o aviso tem que sair
do seu sistema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.x509.oid import NameOID

from nfse_core.signer import CertificateError, load_pfx


def _digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


@dataclass
class InfoCertificado:
    titular: str | None            # Common Name do certificado
    cnpj: str | None               # extraído do CN, quando no formato e-CNPJ
    valido_de: datetime
    valido_ate: datetime
    expirado: bool
    dias_para_expirar: int

    @property
    def alerta(self) -> str | None:
        """Mensagem pronta para a tela, ou None se está tudo bem."""
        if self.expirado:
            return (
                f"Certificado VENCIDO em {self.valido_ate:%d/%m/%Y}. "
                "A emissão de notas está parada até enviar um novo."
            )
        if self.dias_para_expirar <= 30:
            return (
                f"Certificado vence em {self.dias_para_expirar} dia(s) "
                f"({self.valido_ate:%d/%m/%Y}). Providencie a renovação."
            )
        return None


def inspecionar(pfx_base64: str, senha: str | None) -> InfoCertificado:
    """Abre o PFX e devolve o que interessa. Levanta `CertificateError` se o
    arquivo não for um PFX válido ou a senha estiver errada — use isso para
    recusar o upload ANTES de gravar qualquer coisa no banco."""
    _chave, cert, _cadeia = load_pfx(pfx_base64, senha)

    atributos = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    titular = str(atributos[0].value) if atributos else None

    # e-CNPJ ICP-Brasil convenciona CN = "RAZAO SOCIAL:14DIGITOS".
    # É best-effort: a validação oficial exigiria ler o OID ASN.1 dedicado.
    cnpj = None
    if titular and ":" in titular:
        candidato = _digitos(titular.rpartition(":")[2])
        if len(candidato) == 14:
            cnpj = candidato

    valido_de = cert.not_valid_before_utc
    valido_ate = cert.not_valid_after_utc
    agora = datetime.now(timezone.utc)

    return InfoCertificado(
        titular=titular,
        cnpj=cnpj,
        valido_de=valido_de,
        valido_ate=valido_ate,
        expirado=valido_ate < agora,
        dias_para_expirar=(valido_ate - agora).days,
    )


def conferir_titularidade(info: InfoCertificado, cnpj_esperado: str) -> str | None:
    """Avisa quando o certificado é de outro CNPJ. Devolve a mensagem ou None.

    Não é bloqueio: há casos legítimos (matriz assinando por filial). Mas emitir
    com certificado de outro CNPJ é rejeitado pela SEFIN, e é melhor descobrir
    no cadastro do que na primeira nota.
    """
    if not info.cnpj:
        return None
    esperado = _digitos(cnpj_esperado)
    if esperado and info.cnpj != esperado:
        return (
            f"O certificado é do CNPJ {info.cnpj}, diferente do prestador "
            f"configurado ({esperado}). Confirme se é isso mesmo."
        )
    return None
