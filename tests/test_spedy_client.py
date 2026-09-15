import pytest

from app.adapters.spedy_client import SpedyClient, SpedyError


class _RespostaFalsa:
    def __init__(self, status_code: int, corpo):
        self.status_code = status_code
        self._corpo = corpo
        self.text = str(corpo)
        self.content = corpo if isinstance(corpo, bytes) else str(corpo).encode()

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo JSON")
        return self._corpo


@pytest.mark.asyncio
async def test_emitir_nfse_chama_o_path_e_metodo_corretos():
    cliente = SpedyClient("homologacao", "chave-teste")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "nota-1", "status": "enqueued"})

    cliente._request = _request_falso
    resultado = await cliente.emitir_nfse({"description": "Lavagem"})

    assert chamadas == [("POST", "/service-invoices", {"json": {"description": "Lavagem"}})]
    assert resultado == {"id": "nota-1", "status": "enqueued", "_http_status": 200}


@pytest.mark.asyncio
async def test_emitir_nfse_nao_levanta_em_rejeicao_4xx():
    """Rejeicao de negocio (validacao) precisa voltar como dict pro worker
    interpretar -- so falha de transporte/5xx levanta SpedyError."""
    cliente = SpedyClient("homologacao", "chave-teste")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(400, {"processingDetail": {"message": "CNPJ invalido"}})

    cliente._request = _request_falso
    resultado = await cliente.emitir_nfse({})

    assert resultado["_http_status"] == 400
    assert resultado["processingDetail"]["message"] == "CNPJ invalido"


@pytest.mark.asyncio
async def test_emitir_nfse_levanta_spedyerror_em_5xx():
    cliente = SpedyClient("homologacao", "chave-teste")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(503, {"message": "indisponivel"})

    cliente._request = _request_falso
    with pytest.raises(SpedyError):
        await cliente.emitir_nfse({})


@pytest.mark.asyncio
async def test_criar_empresa_desembrulha_o_campo_result():
    cliente = SpedyClient("homologacao", "chave-mestre")

    async def _request_falso(method, path, **kwargs):
        assert (method, path) == ("POST", "/companies")
        return _RespostaFalsa(
            201,
            {"result": {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-nova"}}},
        )

    cliente._request = _request_falso
    resultado = await cliente.criar_empresa({"federalTaxNumber": "12345678000199"})

    assert resultado == {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-nova"}}


@pytest.mark.asyncio
async def test_criar_empresa_levanta_em_erro_de_validacao():
    """Provisionamento e uma acao explicita do admin -- QUALQUER erro (nao so
    5xx) deve virar excecao pro endpoint devolver na hora, sem estado parcial."""
    cliente = SpedyClient("homologacao", "chave-mestre")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(422, {"message": "federalTaxNumber invalido"})

    cliente._request = _request_falso
    with pytest.raises(SpedyError, match="federalTaxNumber invalido"):
        await cliente.criar_empresa({})


@pytest.mark.asyncio
async def test_adicionar_certificado_envia_multipart_com_os_campos_certos():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "cert-1", "isActive": True})

    cliente._request = _request_falso
    await cliente.adicionar_certificado("empresa-1", b"conteudo-pfx", "senha123")

    metodo, caminho, kwargs = chamadas[0]
    assert (metodo, caminho) == ("POST", "/companies/empresa-1/certificates")
    assert kwargs["files"]["certificateFile"] == ("certificado.pfx", b"conteudo-pfx", "application/x-pkcs12")
    assert kwargs["data"] == {"password": "senha123"}


@pytest.mark.asyncio
async def test_configurar_nfse_envelopa_em_serviceinvoice():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"serviceInvoice": {"series": "1"}})

    cliente._request = _request_falso
    await cliente.configurar_nfse("empresa-1", {"series": "1", "environmentType": "simulation"})

    metodo, caminho, kwargs = chamadas[0]
    assert (metodo, caminho) == ("PUT", "/companies/empresa-1/settings")
    assert kwargs["json"] == {"serviceInvoice": {"series": "1", "environmentType": "simulation"}}


@pytest.mark.asyncio
async def test_cancelar_nfse_envia_delete_com_motivo():
    cliente = SpedyClient("homologacao", "chave-empresa")
    chamadas = []

    async def _request_falso(method, path, **kwargs):
        chamadas.append((method, path, kwargs))
        return _RespostaFalsa(200, {"id": "nota-1", "status": "canceled"})

    cliente._request = _request_falso
    resultado = await cliente.cancelar_nfse("nota-1", "Servico nao prestado")

    assert chamadas == [("DELETE", "/service-invoices/nota-1", {"json": {"reason": "Servico nao prestado"}})]
    assert resultado["status"] == "canceled"


@pytest.mark.asyncio
async def test_baixar_pdf_devolve_bytes_em_sucesso():
    cliente = SpedyClient("homologacao", "chave-empresa")

    async def _request_falso(method, path, **kwargs):
        assert (method, path) == ("GET", "/service-invoices/nota-1/pdf")
        return _RespostaFalsa(200, b"%PDF-conteudo")

    cliente._request = _request_falso
    pdf = await cliente.baixar_pdf("nota-1")

    assert pdf == b"%PDF-conteudo"


@pytest.mark.asyncio
async def test_baixar_pdf_levanta_spedyerror_em_falha():
    cliente = SpedyClient("homologacao", "chave-empresa")

    async def _request_falso(method, path, **kwargs):
        return _RespostaFalsa(404, b"nao encontrado")

    cliente._request = _request_falso
    with pytest.raises(SpedyError):
        await cliente.baixar_pdf("nota-1")
