import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import select

from app.models import Emissao, OrigemEmissao, StatusEmissao
from scripts.preencher_dados_stone_xlsx import preencher_dados_stone
from tests.apoio import criar_empresa_e_token

CABECALHO = (
    "DOCUMENTO", "STONECODE", "DATA DA VENDA", "BANDEIRA", "PRODUTO", "STONE ID",
    "N DE PARCELAS", "VALOR BRUTO", "ULTIMO STATUS", "DATA DO ULTIMO STATUS",
    "CODIGO DE AUTORIZACAO",
)


def _xlsx(*linhas: tuple) -> bytes:
    planilha = openpyxl.Workbook()
    aba = planilha.active
    aba.append(CABECALHO)
    for linha in linhas:
        aba.append(linha)
    buffer = io.BytesIO()
    planilha.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_preenche_apenas_emissoes_existentes_e_ainda_sem_data(db_session):
    empresa, _token = await criar_empresa_e_token(db_session)
    db_session.add_all([
        # ja importada antes desses campos existirem -- deve ser preenchida
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("27.98"), competencia=date(2026, 7, 1),
            stone_charge_id="31163337249888",
        ),
        # ja tem data_vencimento preenchida -- nao deve ser sobrescrita
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("13.99"), competencia=date(2026, 7, 1),
            stone_charge_id="31163341016913", data_vencimento=date(2026, 1, 1), produto="Debito",
        ),
    ])
    await db_session.commit()

    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
        ("49055093000140", "477557478", "30/07/2026 17:00", "Elo", "Debito", "31163341016913",
         "1", "13,990000", "Aprovada", "30/07/2026 17:00", "AB124"),
        ("49055093000140", "477557478", "30/07/2026 18:00", "Visa", "Credito", "31163300000000",
         "1", "10,000000", "Aprovada", "30/07/2026 18:00", ""),
    )

    contagem = await preencher_dados_stone(db_session, empresa.id, conteudo)

    assert contagem == {"preenchidas": 1, "ja_preenchidas": 1, "nao_encontradas": 1}

    emissao_1 = (
        await db_session.execute(select(Emissao).where(Emissao.stone_charge_id == "31163337249888"))
    ).scalar_one()
    assert emissao_1.data_vencimento == date(2026, 7, 30)
    assert emissao_1.produto == "Credito"
    assert emissao_1.tipo_produto == "Credito"
    assert emissao_1.bandeira == "Visa"
    assert emissao_1.codigo_autorizacao == "AB123"

    emissao_2 = (
        await db_session.execute(select(Emissao).where(Emissao.stone_charge_id == "31163341016913"))
    ).scalar_one()
    assert emissao_2.data_vencimento == date(2026, 1, 1)
    assert emissao_2.produto == "Debito"
    assert emissao_2.bandeira is None
