from decimal import Decimal

import pytest

from app.models import Cliente, Empresa, EmissaoNfe, ItemEmissaoNfe, Produto, StatusEmissao
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


@pytest.mark.asyncio
async def test_emissao_nfe_com_itens(db_session):
    empresa, _usuario = await criar_empresa_titular(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Comprador", cpf_cnpj="12345678901")
    produto = Produto(empresa_id=empresa.id, codigo_interno="P1", descricao="X",
                      ncm="61091000", cfop_padrao="5102", unidade="UN")
    db_session.add_all([cliente, produto])
    await db_session.flush()

    emissao = EmissaoNfe(empresa_id=empresa.id, cliente_id=cliente.id,
                         serie="1", numero=1, status=StatusEmissao.pendente)
    db_session.add(emissao)
    await db_session.flush()
    item = ItemEmissaoNfe(emissao_nfe_id=emissao.id, produto_id=produto.id,
                          quantidade=Decimal("2"), valor_unitario=Decimal("49.90"),
                          valor_total=Decimal("99.80"), cfop="5102")
    db_session.add(item)
    await db_session.flush()
    assert item.valor_total == Decimal("99.80")


@pytest.mark.asyncio
async def test_emissao_nfe_tem_bookkeeping_de_reemissao_e_item_carrega_aliquota_destino(db_session):
    # Colunas exigidas pelo worker (Task 8): backoff de reemissao automatica
    # em EmissaoNfe e a aliquota interna do destino (venda interestadual)
    # persistida no item entre a criacao da emissao e o processamento.
    empresa, _usuario = await criar_empresa_titular(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Comprador", cpf_cnpj="12345678901", uf="SP")
    produto = Produto(empresa_id=empresa.id, codigo_interno="P1", descricao="X",
                      ncm="61091000", cfop_padrao="6102", unidade="UN")
    db_session.add_all([cliente, produto])
    await db_session.flush()

    emissao = EmissaoNfe(empresa_id=empresa.id, cliente_id=cliente.id,
                         serie="1", numero=1, status=StatusEmissao.pendente)
    db_session.add(emissao)
    await db_session.flush()
    assert emissao.tentativas_reemissao == 0
    assert emissao.proxima_tentativa_em is None

    item = ItemEmissaoNfe(emissao_nfe_id=emissao.id, produto_id=produto.id,
                          quantidade=Decimal("1"), valor_unitario=Decimal("10"),
                          valor_total=Decimal("10.00"), cfop="6102",
                          aliquota_interna_destino=Decimal("18.00"))
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.aliquota_interna_destino == Decimal("18.00")
