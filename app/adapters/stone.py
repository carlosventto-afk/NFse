from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StoneChargePaidEvent:
    charge_id: str
    customer_id: str
    customer_name: str
    valor: Decimal


def parse_stone_charge_paid(payload: dict) -> StoneChargePaidEvent:
    """Extrai os campos documentados publicamente do evento charge.paid.

    Nao inclui CPF/CNPJ do cliente porque o payload de exemplo publico da
    Stone Connect nao o traz. Isso e aceitavel porque o documento do tomador
    e opcional na emissao (ver Task 7 e a spec) — a nota sai sem ele. Este
    parser sera revisado quando o payload real (conta de parceiro ativa)
    confirmar os nomes de campo; se o documento passar a vir no payload,
    o router pode passa-lo direto para `tomador_cpf_cnpj` como um bonus,
    sem exigir nenhuma mudanca estrutural.
    """
    try:
        charge_id = str(payload["id"])
        customer = payload["customer"]
        customer_id = str(customer["id"])
        customer_name = str(customer["name"])
        amount_centavos = int(payload["amount"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"payload da Stone incompleto: falta {exc}") from exc

    return StoneChargePaidEvent(
        charge_id=charge_id,
        customer_id=customer_id,
        customer_name=customer_name,
        valor=Decimal(amount_centavos) / Decimal(100),
    )
