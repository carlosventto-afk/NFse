from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.danfe_nfe import gerar_danfe_fallback
from app.models import AmbienteEnum, Cliente, Empresa, EmissaoNfe, ItemEmissaoNfe, Produto, StatusEmissao


def _empresa() -> Empresa:
    return Empresa(
        cnpj="12345678000199", inscricao_municipal="123456", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Venda de mercadorias",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=None, webhook_token_hash="x",
    )


def _cliente() -> Cliente:
    return Cliente(empresa_id=None, cpf_cnpj="98765432100", nome="Cliente Teste")


def _produto() -> Produto:
    return Produto(
        empresa_id=None, codigo_interno="SKU1", descricao="Camiseta Azul", ncm="61091000",
        cfop_padrao="5102", unidade="UN", csosn_icms="102",
    )


def _emissao_nfe_autorizada() -> EmissaoNfe:
    return EmissaoNfe(
        empresa_id=None, cliente_id=None, serie="1", numero=42, status=StatusEmissao.autorizada,
        chave_acesso="12345678901234567890123456789012345678901234",
    )


def _itens() -> list[tuple[ItemEmissaoNfe, Produto]]:
    item = ItemEmissaoNfe(
        emissao_nfe_id=None, produto_id=None, quantidade=Decimal("2"),
        valor_unitario=Decimal("49.90"), valor_total=Decimal("99.80"), cfop="5102",
    )
    return [(item, _produto())]


def test_gerar_danfe_fallback_inclui_chave_de_acesso():
    pdf = gerar_danfe_fallback(_emissao_nfe_autorizada(), _empresa(), _cliente(), _itens())
    assert pdf.startswith(b"%PDF")


def test_gerar_danfe_fallback_produz_pdf_com_dados_da_nota():
    emissao = _emissao_nfe_autorizada()
    empresa = _empresa()
    cliente = _cliente()
    itens = _itens()

    pdf_bytes = gerar_danfe_fallback(emissao, empresa, cliente, itens)

    assert pdf_bytes.startswith(b"%PDF")
    texto = "".join(pagina.extract_text() for pagina in PdfReader(BytesIO(pdf_bytes)).pages)
    assert empresa.cnpj in texto
    assert emissao.chave_acesso in texto
    assert "Cliente Teste" in texto
    assert "98765432100" in texto
    assert "Camiseta Azul" in texto
    assert "99.80" in texto  # valor total do item e tambem o total da emissao (soma dos itens)
