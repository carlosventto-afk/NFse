from datetime import datetime, timezone
from decimal import Decimal

from lxml import etree

from nfe_core import NFE_NS, NfeData, NfeItemData, build_nfe_xml, sign_nfe
from nfse_core.signer import DS_NS
from tests.test_nfse_core_signer import _pfx_teste_base64


def _nfe_data() -> NfeData:
    return NfeData(
        tp_amb=2, c_uf_emit="15", dh_emi=datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc),
        serie="1", numero=42, emit_cnpj="12345678000199", emit_ie="123456789", emit_crt=1,
        emit_uf="PA", dest_cpf_cnpj="98765432100", dest_nome="Cliente Teste", dest_uf="PA",
        dest_ie=None,
        itens=[NfeItemData(
            n_item=1, c_prod="SKU1", descricao="Produto", ncm="12345678", cfop="5102",
            unidade="UN", quantidade=Decimal("1"), valor_unitario=Decimal("10"),
            valor_total=Decimal("10.00"), cst_icms=None, csosn_icms="102",
            base_icms=Decimal("10.00"), valor_icms=None, valor_icms_uf_remetente=None,
            valor_icms_uf_destino=None, valor_fcp=None,
        )],
    )


def test_sign_nfe_anexa_signature_como_irma_de_infnfe():
    xml = build_nfe_xml(_nfe_data())

    assinado = sign_nfe(xml, _pfx_teste_base64(), "senha123")

    root = etree.fromstring(assinado)
    assert root.tag == f"{{{NFE_NS}}}NFe"
    inf = root.find(f"{{{NFE_NS}}}infNFe")
    signature = root.find(f"{{{DS_NS}}}Signature")
    assert signature is not None
    assert signature.getparent() is root
    assert inf.find(f".//{{{DS_NS}}}Signature") is None
    assert signature.find(f".//{{{DS_NS}}}Reference").get("URI") == f"#{inf.get('Id')}"
    assert inf.get("Id").startswith("NFe") and len(inf.get("Id")) == 47
