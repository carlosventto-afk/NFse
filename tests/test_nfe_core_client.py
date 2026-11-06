from types import SimpleNamespace
from unittest.mock import patch

from nfe_core.client import AmbienteEnum, SefazClient, UF_ENDPOINTS


def _resposta_lote_sincrono(c_stat_lote: str, c_stat_nfe: str, x_motivo_nfe: str, n_prot: str | None):
    """Forma realista de retEnviNFe sincrono: cStat/xMotivo do TOPO sao do
    LOTE (104 = lote processado); o status da NF-e mora em protNFe.infProt."""
    return SimpleNamespace(
        cStat=c_stat_lote, xMotivo="Lote processado",
        protNFe=SimpleNamespace(infProt=SimpleNamespace(cStat=c_stat_nfe, xMotivo=x_motivo_nfe, nProt=n_prot)),
    )


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


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_le_cstat_da_nfe_em_protnfe_e_nao_o_do_lote(mock_zeep_client):
    mock_zeep_client.return_value.service.nfeAutorizacaoLote.return_value = _resposta_lote_sincrono(
        "104", "100", "Autorizado o uso da NF-e", "115260000000001",
    )
    resposta = await SefazClient().autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    assert resposta.autorizada is True
    assert resposta.c_stat == "100"
    assert resposta.x_motivo == "Autorizado o uso da NF-e"
    assert resposta.protocolo == "115260000000001"


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_rejeicao_da_nfe_dentro_de_lote_processado(mock_zeep_client):
    mock_zeep_client.return_value.service.nfeAutorizacaoLote.return_value = _resposta_lote_sincrono(
        "104", "225", "Falha no Schema XML", None,
    )
    resposta = await SefazClient().autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    assert resposta.autorizada is False
    assert (resposta.c_stat, resposta.x_motivo) == ("225", "Falha no Schema XML")


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_sem_protnfe_cai_no_cstat_do_topo(mock_zeep_client):
    # Lote assincrono (103 = recebido) ou erro de lote: nao ha protNFe ainda.
    # zeep devolve elemento opcional ausente como None.
    mock_zeep_client.return_value.service.nfeAutorizacaoLote.return_value = SimpleNamespace(
        cStat="103", xMotivo="Lote recebido com sucesso", protNFe=None,
    )
    resposta = await SefazClient().autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    assert resposta.autorizada is False
    assert (resposta.c_stat, resposta.x_motivo, resposta.protocolo) == ("103", "Lote recebido com sucesso", None)


@patch("nfe_core.client.zeep.Client")
async def test_consultar_protocolo_le_cstat_de_protnfe(mock_zeep_client):
    mock_zeep_client.return_value.service.nfeConsultaNF.return_value = _resposta_lote_sincrono(
        "100", "100", "Autorizado o uso da NF-e", "555",
    )
    resposta = await SefazClient().consultar_protocolo("4321" * 11, uf="PA", ambiente=AmbienteEnum.homologacao)
    assert resposta.autorizada is True
    assert (resposta.c_stat, resposta.protocolo) == ("100", "555")


@patch("nfe_core.client.zeep.Client")
async def test_consultar_protocolo_nfe_inexistente_cai_no_cstat_do_topo(mock_zeep_client):
    # 217 = NF-e nao consta na base: sem protNFe na resposta (atributo ausente).
    mock_zeep_client.return_value.service.nfeConsultaNF.return_value = SimpleNamespace(
        cStat="217", xMotivo="Rejeicao: NF-e nao consta na base de dados da SEFAZ",
    )
    resposta = await SefazClient().consultar_protocolo("4321" * 11, uf="PA", ambiente=AmbienteEnum.homologacao)
    assert resposta.autorizada is False
    assert resposta.c_stat == "217"
    assert resposta.protocolo is None


@patch("nfe_core.client.zeep.Client")
async def test_autorizar_cria_zeep_client_com_timeout(mock_zeep_client):
    # Sem timeout, uma SEFAZ travada prende o loop_worker compartilhado
    # (inclusive a fila da NFS-e). Mesmo valor do cliente SEFIN (nfse_core).
    await SefazClient().autorizar(b"<xml/>", uf="PA", ambiente=AmbienteEnum.homologacao)
    transport = mock_zeep_client.call_args.kwargs["transport"]
    assert transport.load_timeout == 60
    assert transport.operation_timeout == 60


@patch("nfe_core.client.zeep.Client")
async def test_consultar_protocolo_cria_zeep_client_com_timeout(mock_zeep_client):
    await SefazClient().consultar_protocolo("4321" * 11, uf="PA", ambiente=AmbienteEnum.homologacao)
    transport = mock_zeep_client.call_args.kwargs["transport"]
    assert transport.load_timeout == 60
    assert transport.operation_timeout == 60
