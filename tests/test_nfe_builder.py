import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.adapters.nfe_builder import ItemPedido, montar_nfe_data
from app.models import AmbienteEnum, Cliente, Empresa, Produto


def _empresa(crt: int = 3, uf: str = "PA") -> Empresa:
    return Empresa(
        cnpj="12345678000199", municipio_ibge="1501402",
        op_simp_nac=3 if crt == 3 else 1, codigo_tributacao="141001",
        descricao_servico_padrao="Venda de mercadoria", ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado="x", certificado_senha_cifrada="x",
        certificado_valido_ate=datetime.now(timezone.utc), webhook_token_hash="x",
        inscricao_estadual="123456789", crt=crt, uf=uf,
    )


def _cliente(uf: str = "PA") -> Cliente:
    return Cliente(
        empresa_id=uuid.uuid4(), cpf_cnpj="98765432100", nome="Cliente Teste", uf=uf,
    )


def _produto(
    eh_substituicao_tributaria: bool = False,
    cst_icms: str | None = "020",
    csosn_icms: str | None = None,
) -> Produto:
    return Produto(
        id=uuid.uuid4(), empresa_id=uuid.uuid4(), codigo_interno="SKU1",
        descricao="Produto Teste", ncm="12345678", cfop_padrao="5102", unidade="UN",
        cst_icms=cst_icms, csosn_icms=csosn_icms, valor_unitario_padrao=Decimal("10.00"),
        eh_substituicao_tributaria=eh_substituicao_tributaria,
    )


empresa = _empresa()
cliente = _cliente()


def test_monta_nfe_data_produto_com_substituicao_tributaria_levanta_erro():
    produto = _produto(eh_substituicao_tributaria=True)
    with pytest.raises(ValueError, match="Substituicao Tributaria"):
        montar_nfe_data(
            empresa, cliente, "1", 1, {produto.id: produto},
            [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
        )


@pytest.mark.parametrize("crt,cst_icms,csosn_icms", [(1, None, "101"), (3, "020", None)])
def test_monta_nfe_data_usa_crt_da_empresa_pra_escolher_cst_ou_csosn(crt, cst_icms, csosn_icms):
    empresa = _empresa(crt=crt)
    produto = _produto(csosn_icms=csosn_icms, cst_icms=cst_icms)
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
    )
    assert data.itens[0].csosn_icms == csosn_icms
    assert data.itens[0].cst_icms == cst_icms


def test_monta_nfe_data_mapeia_campos_de_empresa_cliente_e_item():
    produto = _produto()
    data = montar_nfe_data(
        empresa, cliente, "7", 42, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("3"), valor_unitario_override=None)],
    )

    assert data.tp_amb == 2  # homologacao
    assert data.c_uf_emit == "15"  # 2 primeiros digitos do municipio_ibge (Belem/PA)
    assert data.serie == "7"
    assert data.numero == 42
    assert data.emit_cnpj == "12345678000199"
    assert data.emit_ie == "123456789"
    assert data.emit_crt == 3
    assert data.emit_uf == "PA"
    assert data.dest_cpf_cnpj == "98765432100"
    assert data.dest_nome == "Cliente Teste"
    assert data.dest_uf == "PA"

    item = data.itens[0]
    assert item.n_item == 1
    assert item.c_prod == "SKU1"
    assert item.ncm == "12345678"
    assert item.cfop == "5102"
    assert item.unidade == "UN"
    assert item.quantidade == Decimal("3")
    assert item.valor_unitario == Decimal("10.00")
    assert item.valor_total == Decimal("30.00")
    # venda interna (mesma UF emitente/destinatario) -- sem partilha de ICMS
    assert item.valor_icms_uf_destino is None
    assert item.valor_fcp is None


def test_monta_nfe_data_usa_valor_unitario_override_quando_informado():
    produto = _produto()
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("2"), valor_unitario_override=Decimal("25.00"))],
    )

    item = data.itens[0]
    assert item.valor_unitario == Decimal("25.00")
    assert item.valor_total == Decimal("50.00")


def test_monta_nfe_data_interestadual_usa_aliquota_interna_informada():
    empresa_pa = _empresa(uf="PA")
    cliente_sp = _cliente(uf="SP")
    produto = _produto()
    data = montar_nfe_data(
        empresa_pa, cliente_sp, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None,
                     aliquota_interna_destino=Decimal("18.00"))],
    )
    item = data.itens[0]
    assert item.valor_icms_uf_destino is not None
    assert item.valor_icms_uf_destino > 0


def test_monta_nfe_data_interestadual_sem_aliquota_interna_levanta_erro():
    empresa_pa = _empresa(uf="PA")
    cliente_sp = _cliente(uf="SP")
    produto = _produto()
    with pytest.raises(ValueError, match="aliquota interna"):
        montar_nfe_data(
            empresa_pa, cliente_sp, "1", 1, {produto.id: produto},
            [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
        )


def test_monta_nfe_data_usa_cfop_override_do_item_quando_informado():
    # Venda interestadual do mesmo produto usa 6xxx em vez do 5xxx padrao --
    # o CFOP persistido no item da emissao precisa prevalecer.
    produto = _produto()
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None,
                     cfop_override="6102")],
    )
    assert data.itens[0].cfop == "6102"


def test_monta_nfe_data_sem_cfop_override_usa_cfop_padrao_do_produto():
    produto = _produto()
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
    )
    assert data.itens[0].cfop == "5102"


def test_monta_nfe_data_usa_dh_emi_informado():
    produto = _produto()
    dh_emi = datetime(2026, 9, 15, 13, 30, tzinfo=timezone.utc)
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
        dh_emi=dh_emi,
    )
    assert data.dh_emi == dh_emi


def test_monta_nfe_data_sem_dh_emi_usa_agora():
    produto = _produto()
    antes = datetime.now(timezone.utc)
    data = montar_nfe_data(
        empresa, cliente, "1", 1, {produto.id: produto},
        [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
    )
    assert antes <= data.dh_emi <= datetime.now(timezone.utc)


def test_monta_nfe_data_sem_preco_disponivel_levanta_erro():
    produto = _produto()
    produto.valor_unitario_padrao = None
    with pytest.raises(ValueError, match="valor_unitario"):
        montar_nfe_data(
            empresa, cliente, "1", 1, {produto.id: produto},
            [ItemPedido(produto_id=produto.id, quantidade=Decimal("1"), valor_unitario_override=None)],
        )
