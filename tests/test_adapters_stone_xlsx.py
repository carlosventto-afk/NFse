import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from app.adapters.stone_xlsx import CabecalhoInvalidoError, parsear_relatorio_stone

CABECALHO = (
    "DOCUMENTO", "STONECODE", "DATA DA VENDA", "BANDEIRA", "PRODUTO", "STONE ID",
    "N DE PARCELAS", "VALOR BRUTO", "ULTIMO STATUS", "DATA DO ULTIMO STATUS",
    # cabecalho intencionalmente com acentuacao corrompida, igual ao
    # exportado pela Stone de verdade -- ver _normalizar_cabecalho.
    "C�DIGO DE AUTORIZA��O",
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


def test_parseia_linhas_aprovadas_e_deriva_tipo_produto():
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 20:30", "Visa", "Credito", "31263373356039",
         "1", "27,980000", "Aprovada", "30/07/2026 20:30", "QS9B9I"),
        ("49055093000140", "477557478", "30/07/2026 21:01", "Elo", "Debito", "31363374170391",
         "1", "13,990000", "Aprovada", "30/07/2026 21:01", "118928"),
        ("49055093000140", "", "30/07/2026 21:10", "", "Pix QRcode", "E20855875202608010010JRP9QI2JJDR",
         "", "13,990000", "Aprovada", "30/07/2026 21:10", ""),
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.ignoradas == {"status_nao_aprovado": 0, "linha_invalida": 0}
    assert len(resultado.notas) == 3

    credito, debito, pix = resultado.notas
    assert credito.tipo_produto == "Credito"
    assert credito.bandeira == "Visa"
    assert credito.codigo_autorizacao == "QS9B9I"
    assert credito.data_da_venda == datetime(2026, 7, 30, 20, 30)
    assert credito.data_vencimento == date(2026, 7, 30)
    assert credito.valor == Decimal("27.98")

    assert debito.tipo_produto == "Debito"

    assert pix.produto == "Pix QRcode"
    assert pix.tipo_produto == "PIX"
    assert pix.bandeira is None
    assert pix.codigo_autorizacao is None


def test_ignora_linha_com_status_diferente_de_aprovada():
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 20:30", "Visa", "Credito", "31263373356039",
         "1", "27,980000", "Negada", "30/07/2026 20:30", ""),
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["status_nao_aprovado"] == 1


def test_ignora_linha_invalida_sem_travar_o_arquivo_inteiro():
    conteudo = _xlsx(
        ("49055093000140", "477557478", "data-invalida", "Visa", "Credito", "31263373356039",
         "1", "27,980000", "Aprovada", "30/07/2026 20:30", ""),
        ("49055093000140", "477557478", "30/07/2026 20:30", "Visa", "Credito", "31263373356040",
         "1", "27,980000", "Aprovada", "30/07/2026 20:30", ""),
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    assert resultado.ignoradas["linha_invalida"] == 1


def test_cabecalho_sem_coluna_obrigatoria_levanta_erro():
    planilha = openpyxl.Workbook()
    aba = planilha.active
    aba.append(("DOCUMENTO", "OUTRA COLUNA"))
    aba.append(("x", "y"))
    buffer = io.BytesIO()
    planilha.save(buffer)

    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(buffer.getvalue())


def test_arquivo_corrompido_levanta_erro():
    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(b"isso nao e um xlsx")
