from unittest.mock import patch

from nfe_core.client import AmbienteEnum, SefazClient, UF_ENDPOINTS


def test_uf_endpoints_cobre_todas_as_27_ufs():
    assert len(UF_ENDPOINTS) == 27
    assert "PA" in UF_ENDPOINTS


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_usa_endpoint_de_homologacao_quando_ambiente_homologacao(mock_zeep_client):
    client = SefazClient()
    await client.autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    chamada_url = mock_zeep_client.call_args[0][0]
    assert chamada_url == UF_ENDPOINTS["PA"]["autorizacao_homologacao"]


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_usa_endpoint_de_producao_quando_ambiente_producao(mock_zeep_client):
    client = SefazClient()
    await client.autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.producao)
    chamada_url = mock_zeep_client.call_args[0][0]
    assert chamada_url == UF_ENDPOINTS["PA"]["autorizacao_producao"]


@patch("nfe_core.client.zeep.Client")
async def test_consultar_protocolo_usa_endpoint_de_consulta_homologacao(mock_zeep_client):
    client = SefazClient()
    await client.consultar_protocolo("4321" * 11, uf="PA", ambiente=AmbienteEnum.homologacao)
    chamada_url = mock_zeep_client.call_args[0][0]
    assert chamada_url == UF_ENDPOINTS["PA"]["consulta_protocolo_homologacao"]
