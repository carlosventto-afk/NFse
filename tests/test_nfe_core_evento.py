"""Testes de nfe_core.evento: evento de cancelamento da NF-e."""
import pytest
from lxml import etree

from nfe_core.evento import (
    NFE_NS,
    EventoCancelamentoNfeData,
    build_evento_cancelamento_nfe_xml,
)


def _data(**overrides) -> EventoCancelamentoNfeData:
    kwargs = {
        "chave_acesso": "4" * 44,
        "protocolo_autorizacao": "135260000000001",
        "justificativa": "Erro de digitação no valor da nota fiscal",
    }
    kwargs.update(overrides)
    return EventoCancelamentoNfeData(**kwargs)


def test_justificativa_curta_levanta_erro():
    with pytest.raises(ValueError, match="15 caracteres"):
        build_evento_cancelamento_nfe_xml(EventoCancelamentoNfeData(
            chave_acesso="4" * 44, protocolo_autorizacao="123", justificativa="curta"))


def test_chave_acesso_invalida_levanta_erro():
    with pytest.raises(ValueError, match="44"):
        build_evento_cancelamento_nfe_xml(_data(chave_acesso="123"))


def test_protocolo_vazio_levanta_erro():
    with pytest.raises(ValueError, match="protocolo"):
        build_evento_cancelamento_nfe_xml(_data(protocolo_autorizacao="   "))


def test_xml_contem_tags_esperadas_com_valores_corretos():
    data = _data()
    xml = build_evento_cancelamento_nfe_xml(data)
    root = etree.fromstring(xml)

    def find(tag):
        return root.find(f".//{{{NFE_NS}}}{tag}")

    assert find("chNFe").text == "4" * 44
    assert find("nProt").text == data.protocolo_autorizacao
    assert find("xJust").text == data.justificativa
    assert find("tpEvento").text == "110111"
    assert find("nSeqEvento").text == "1"
    assert find("descEvento").text == "Cancelamento"

    inf_evento = root.find(f".//{{{NFE_NS}}}infEvento")
    assert inf_evento.get("Id") == data.id_evento
    assert inf_evento.get("Id").startswith("ID110111")


def test_id_evento_tem_formato_esperado():
    data = _data()
    assert data.id_evento == f"ID110111{'4' * 44}01"
