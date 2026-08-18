from datetime import date, datetime
from decimal import Decimal

import pytest

from app.adapters.stone_csv import CabecalhoInvalidoError, parsear_relatorio_stone

CABECALHO = (
    "CATEGORIA;DATA DA VENDA;DATA DE VENCIMENTO;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;"
    "ÚLTIMO STATUS;DATA DO ÚLTIMO STATUS"
)


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


def test_parsear_linha_valida_unica_gera_uma_nota():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31/07/2026;31163337249888;1;1;27,980000;Pago;31/07/2026 09:00:00"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    nota = resultado.notas[0]
    assert nota.stone_charge_id == "31163337249888"
    assert nota.data_da_venda == datetime(2026, 7, 30, 14, 30, 4)
    assert nota.data_vencimento == date(2026, 7, 31)
    assert nota.data_ultimo_status == datetime(2026, 7, 31, 9, 0, 0)
    assert nota.valor == Decimal("27.980000")
    assert resultado.ignoradas == {
        "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
    }


def test_parsear_ignora_linha_com_status_diferente_de_pago():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31/07/2026;31163337249888;1;1;27,980000;Estornado;30/07/2026 14:30:04"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["status_nao_pago"] == 1


def test_parsear_ignora_linha_com_categoria_diferente_de_venda():
    conteudo = _csv(
        "Ajuste Financeiro;30/07/2026 14:30:04;31/07/2026;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["categoria_nao_venda"] == 1


def test_parsear_agrupa_parcelas_da_mesma_venda_somando_o_valor():
    conteudo = _csv(
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476401;3;1;41,970000;Pago;23/07/2026 08:00:00",
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476402;3;2;41,970000;Pago;23/07/2026 08:00:00",
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476403;3;3;41,960000;Pago;23/07/2026 08:00:00",
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    nota = resultado.notas[0]
    # chave de dedupe vem da parcela numero 1 do grupo, nao da ultima linha lida
    assert nota.stone_charge_id == "31063343476401"
    assert nota.valor == Decimal("125.900000")


def test_parsear_nao_agrupa_vendas_distintas_com_mesma_data_e_qtd_parcelas_diferente():
    conteudo = _csv(
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476401;1;1;10,000000;Pago;22/07/2026 18:17:45",
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476402;1;1;20,000000;Pago;22/07/2026 18:17:45",
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 2


def test_parsear_ignora_linha_com_valor_invalido():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31/07/2026;31163337249888;1;1;nao-e-um-numero;Pago;30/07/2026 14:30:04"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["linha_invalida"] == 1


def test_parsear_ignora_linha_com_data_invalida():
    conteudo = _csv(
        "Venda;30-07-2026;31/07/2026;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["linha_invalida"] == 1


def test_parsear_ignora_linha_com_data_de_vencimento_invalida():
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31-07-2026;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04"
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas["linha_invalida"] == 1


def test_parsear_arquivo_sem_coluna_obrigatoria_levanta_erro():
    conteudo = "﻿CATEGORIA;DATA DA VENDA\nVenda;30/07/2026 14:30:04\n".encode("utf-8")

    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(conteudo)


def test_parsear_arquivo_fora_de_utf8_levanta_erro():
    conteudo = "CATEGORIA;DATA DA VENDA".encode("utf-16")

    with pytest.raises(CabecalhoInvalidoError):
        parsear_relatorio_stone(conteudo)


def test_parsear_grupo_usa_data_do_ultimo_status_da_primeira_parcela():
    conteudo = _csv(
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476401;2;1;10,000000;Pago;25/07/2026 09:00:00",
        "Venda;22/07/2026 18:17:45;31/07/2026;31063343476402;2;2;10,000000;Pago;26/07/2026 09:00:00",
    )

    resultado = parsear_relatorio_stone(conteudo)

    assert len(resultado.notas) == 1
    assert resultado.notas[0].data_ultimo_status == datetime(2026, 7, 25, 9, 0, 0)


def test_parsear_arquivo_vazio_nao_gera_notas_nem_erro():
    conteudo = _csv()

    resultado = parsear_relatorio_stone(conteudo)

    assert resultado.notas == []
    assert resultado.ignoradas == {
        "status_nao_pago": 0, "categoria_nao_venda": 0, "linha_invalida": 0,
    }
