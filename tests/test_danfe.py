from datetime import date
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.danfe import gerar_danfse_fallback
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao


def test_gerar_danfse_fallback_produz_pdf_com_dados_da_nota():
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="123456", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=None, webhook_token_hash="x",
    )
    emissao = Emissao(
        empresa_id=None, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=42, chave_acesso="12345678901234567890123456789012345678901234567890",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste",
        descricao="Lavagem de 5kg de roupa", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )

    pdf_bytes = gerar_danfse_fallback(emissao, empresa)

    assert pdf_bytes.startswith(b"%PDF")
    texto = "".join(pagina.extract_text() for pagina in PdfReader(BytesIO(pdf_bytes)).pages)
    assert "Cliente Teste" in texto
    assert "49.90" in texto
    assert emissao.chave_acesso in texto
