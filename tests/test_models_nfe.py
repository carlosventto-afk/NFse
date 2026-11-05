from decimal import Decimal

import pytest

from app.models import Empresa, Produto
from tests.apoio import criar_empresa_titular


@pytest.mark.asyncio
async def test_empresa_aceita_ie_crt_uf(db_session):
    empresa, _usuario = await criar_empresa_titular(
        db_session, inscricao_estadual="123456789", crt=3, uf="PA"
    )
    assert isinstance(empresa, Empresa)
    assert empresa.inscricao_estadual == "123456789"
    assert empresa.crt == 3
    assert empresa.uf == "PA"


@pytest.mark.asyncio
async def test_produto_normal_usa_cst_sn_usa_csosn(db_session):
    empresa, _usuario = await criar_empresa_titular(db_session)
    produto = Produto(
        empresa_id=empresa.id, codigo_interno="P1", descricao="Camiseta",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
        cst_icms=None, csosn_icms="101", valor_unitario_padrao=Decimal("49.90"),
    )
    db_session.add(produto)
    await db_session.flush()
    assert produto.csosn_icms == "101"
    assert produto.cst_icms is None
