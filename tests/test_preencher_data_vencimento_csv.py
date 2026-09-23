from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Emissao, OrigemEmissao, StatusEmissao
from scripts.preencher_data_vencimento_csv import preencher_data_vencimento
from tests.apoio import criar_empresa_e_token

CABECALHO = (
    "CATEGORIA;DATA DA VENDA;DATA DE VENCIMENTO;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;"
    "ÚLTIMO STATUS;DATA DO ÚLTIMO STATUS"
)


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


@pytest.mark.asyncio
async def test_preenche_apenas_emissoes_existentes_e_ainda_sem_data(db_session):
    empresa, _token = await criar_empresa_e_token(db_session)
    db_session.add_all([
        # ja importada antes do campo existir -- deve ser preenchida
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("27.98"), competencia=date(2026, 7, 1),
            stone_charge_id="31163337249888",
        ),
        # ja tem data_vencimento preenchida -- nao deve ser sobrescrita
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("13.99"), competencia=date(2026, 7, 1),
            stone_charge_id="31163341016913", data_vencimento=date(2026, 1, 1),
        ),
    ])
    await db_session.commit()

    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31/07/2026;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04",
        "Venda;30/07/2026 17:00:47;31/07/2026;31163341016913;1;1;13,990000;Pago;30/07/2026 17:00:47",
        "Venda;30/07/2026 18:00:00;31/07/2026;31163300000000;1;1;10,000000;Pago;30/07/2026 18:00:00",
    )

    contagem = await preencher_data_vencimento(db_session, empresa.id, conteudo)

    assert contagem == {"preenchidas": 1, "ja_preenchidas": 1, "nao_encontradas": 1}

    emissao_1 = (
        await db_session.execute(select(Emissao).where(Emissao.stone_charge_id == "31163337249888"))
    ).scalar_one()
    assert emissao_1.data_vencimento == date(2026, 7, 31)

    emissao_2 = (
        await db_session.execute(select(Emissao).where(Emissao.stone_charge_id == "31163341016913"))
    ).scalar_one()
    assert emissao_2.data_vencimento == date(2026, 1, 1)
