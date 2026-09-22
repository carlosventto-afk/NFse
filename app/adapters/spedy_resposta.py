"""Leitura tolerante das respostas da Spedy -- mesmo espirito de
nfse_core/resposta.py. Os nomes de campo do estado FINAL (autorizada) nao
estao 100% confirmados pela documentacao publica; ajustar as chaves
candidatas abaixo apos a validacao ao vivo com o sandbox (Task 5, ultimo
passo deste arquivo do plano)."""
from __future__ import annotations


def interpretar_status_emissao(bruta: dict) -> str:
    """Devolve "authorized", "rejected" ou "pending" (qualquer outro status
    da Spedy, incluindo "enqueued"/"processing"/campo ausente)."""
    status = bruta.get("status")
    if status == "authorized":
        return "authorized"
    if status in ("rejected", "denied"):
        return "rejected"
    return "pending"


def interpretar_status_cancelamento(bruta: dict) -> str:
    """Devolve "canceled", "failed" ou "pending".

    Diferente de interpretar_status_emissao: o campo `status` de nivel
    superior e o status da NOTA em si, que continua "authorized" mesmo
    quando so o CANCELAMENTO e recusado (confirmado ao vivo em Belem: prazo
    de cancelamento expirado, L999) -- o resultado do cancelamento vem em
    processingDetail.status."""
    if bruta.get("status") == "canceled":
        return "canceled"
    if (bruta.get("processingDetail") or {}).get("status") == "failed":
        return "failed"
    return "pending"


def chave_acesso_de(bruta: dict) -> str | None:
    for chave in ("accessKey", "chaveAcesso", "nfseAccessKey"):
        valor = bruta.get(chave)
        if valor:
            return str(valor)
    return None
