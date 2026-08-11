from decimal import Decimal

import pytest

from app.adapters.stone import parse_stone_charge_paid


def test_parse_stone_charge_paid_extrai_campos_documentados():
    payload = {
        "id": "ch_123abc",
        "amount": 4990,
        "customer": {"id": "cus_456", "name": "Fulano de Tal"},
    }

    evento = parse_stone_charge_paid(payload)

    assert evento.charge_id == "ch_123abc"
    assert evento.customer_id == "cus_456"
    assert evento.customer_name == "Fulano de Tal"
    assert evento.valor == Decimal("49.90")


def test_parse_stone_charge_paid_rejeita_payload_incompleto():
    with pytest.raises(ValueError, match="payload"):
        parse_stone_charge_paid({"id": "ch_123abc"})
