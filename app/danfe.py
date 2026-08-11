from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models import Emissao, Empresa


def gerar_danfse_fallback(emissao: Emissao, empresa: Empresa) -> bytes:
    """Representacao propria da nota quando a API do ADN nao responde.

    Nao e o documento fiscal (o XML e) — e so uma representacao legivel.
    """
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    y = altura - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "NFS-e Nacional — Representacao (DANFSe indisponivel)")
    y -= 30

    pdf.setFont("Helvetica", 10)
    linhas = [
        f"Prestador: CNPJ {empresa.cnpj}",
        f"Serie/Numero: {emissao.serie}/{emissao.numero}",
        f"Chave de acesso: {emissao.chave_acesso or '-'}",
        f"Tomador: {emissao.tomador_nome or '-'} ({emissao.tomador_cpf_cnpj or 'nao informado'})",
        f"Descricao do servico: {emissao.descricao}",
        f"Valor: R$ {emissao.valor:.2f}",
        f"Competencia: {emissao.competencia:%m/%Y}",
    ]
    for linha in linhas:
        pdf.drawString(50, y, linha)
        y -= 20

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
