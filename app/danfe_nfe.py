from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.models import Cliente, Empresa, EmissaoNfe, ItemEmissaoNfe, Produto


def gerar_danfe_fallback(
    emissao: EmissaoNfe,
    empresa: Empresa,
    cliente: Cliente,
    itens: list[tuple[ItemEmissaoNfe, Produto]],
) -> bytes:
    """Representacao propria da NF-e quando a SEFAZ nao responde.

    Nao e o DANFE oficial nem o documento fiscal (o XML e) — e so uma
    representacao legivel. `EmissaoNfe`/`ItemEmissaoNfe` nao tem relacionamento
    ORM entre si (ver app/worker.py), por isso o destinatario e os itens
    chegam como parametros em vez de serem consultados aqui.
    """
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    y = altura - 50
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "NF-e — Representacao (DANFE indisponivel)")
    y -= 30

    pdf.setFont("Helvetica", 10)
    valor_total = sum((item.valor_total for item, _ in itens), Decimal("0"))
    linhas = [
        f"Emitente: CNPJ {empresa.cnpj}",
        f"Serie/Numero: {emissao.serie}/{emissao.numero}",
        f"Chave de acesso: {emissao.chave_acesso or '-'}",
        f"Destinatario: {cliente.nome} ({cliente.cpf_cnpj or 'nao informado'})",
    ]
    for linha in linhas:
        pdf.drawString(50, y, linha)
        y -= 20

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Itens")
    y -= 20
    pdf.setFont("Helvetica", 10)
    for item, produto in itens:
        linha = (
            f"{produto.descricao} — CFOP {item.cfop} — Qtd {item.quantidade} x "
            f"R$ {item.valor_unitario:.2f} = R$ {item.valor_total:.2f}"
        )
        pdf.drawString(50, y, linha)
        y -= 20

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, f"Valor total: R$ {valor_total:.2f}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
