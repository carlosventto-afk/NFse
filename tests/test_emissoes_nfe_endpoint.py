import functools
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Cliente, EmissaoNfe, ItemEmissaoNfe, PapelUsuario, Produto, StatusEmissao
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


async def _criar_cliente(db_session, empresa, **overrides) -> Cliente:
    dados = dict(empresa_id=empresa.id, nome="Cliente Teste", cpf_cnpj="12345678901", uf="SP")
    dados.update(overrides)
    cliente = Cliente(**dados)
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)
    return cliente


async def _criar_produto(db_session, empresa, **overrides) -> Produto:
    dados = dict(
        empresa_id=empresa.id, codigo_interno="P1", descricao="Camiseta", ncm="61091000",
        cfop_padrao="5102", unidade="UN", csosn_icms="102",
    )
    dados.update(overrides)
    produto = Produto(**dados)
    db_session.add(produto)
    await db_session.commit()
    await db_session.refresh(produto)
    return produto


async def _criar_emissao(db_session, empresa, cliente, **overrides) -> EmissaoNfe:
    dados = dict(
        empresa_id=empresa.id, cliente_id=cliente.id, serie="1", numero=1,
        status=StatusEmissao.aguardando_emissao,
    )
    dados.update(overrides)
    emissao = EmissaoNfe(**dados)
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


async def _requisitar(db_session, metodo: str, url: str, token: str, **kwargs):
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                metodo, url, headers={"Authorization": f"Bearer {token}"}, **kwargs
            )
    finally:
        app.dependency_overrides.clear()


# --- POST /emissoes-nfe -------------------------------------------------------


@pytest.mark.asyncio
async def test_criar_emissao_com_produto_de_outra_empresa_e_rejeitado(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, _token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_a = await _criar_cliente(db_session, empresa_a)
    produto_de_outra_empresa = await _criar_produto(
        db_session, empresa_b, codigo_interno="PB", valor_unitario_padrao=Decimal("10"),
    )

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token_a,
        json={"cliente_id": str(cliente_a.id),
              "itens": [{"produto_id": str(produto_de_outra_empresa.id), "quantidade": "1"}]},
    )

    assert resposta.status_code == 404
    total = (await db_session.execute(select(EmissaoNfe))).scalars().all()
    assert total == []


@pytest.mark.asyncio
async def test_criar_emissao_com_cliente_de_outra_empresa_e_rejeitado(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, _token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_de_b = await _criar_cliente(db_session, empresa_b)
    produto_a = await _criar_produto(db_session, empresa_a, valor_unitario_padrao=Decimal("10"))

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token_a,
        json={"cliente_id": str(cliente_de_b.id),
              "itens": [{"produto_id": str(produto_a.id), "quantidade": "1"}]},
    )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_criar_emissao_fica_aguardando_emissao_pro_worker(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    produto_padrao = await _criar_produto(
        db_session, empresa, codigo_interno="P1", valor_unitario_padrao=Decimal("10.5000"),
    )
    produto_override = await _criar_produto(
        db_session, empresa, codigo_interno="P2", valor_unitario_padrao=Decimal("99"),
    )

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token,
        json={
            "cliente_id": str(cliente.id),
            "itens": [
                # Sem override: cai no valor_unitario_padrao/cfop_padrao do produto.
                {"produto_id": str(produto_padrao.id), "quantidade": "3"},
                # Com override: o valor/CFOP informados prevalecem.
                {"produto_id": str(produto_override.id), "quantidade": "1.5",
                 "valor_unitario_override": "2.3333", "cfop_override": "6102",
                 "aliquota_interna_destino": "18"},
            ],
        },
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["status"] == "aguardando_emissao"
    assert corpo["cliente_id"] == str(cliente.id)
    # Sequencia PROPRIA da NF-e (serie_nfe/proximo_numero_nfe), nao a da NFS-e.
    assert corpo["serie"] == "1"
    assert corpo["numero"] == 1
    assert len(corpo["itens"]) == 2

    emissao = await db_session.get(EmissaoNfe, corpo["id"])
    assert emissao.empresa_id == empresa.id
    assert emissao.status == StatusEmissao.aguardando_emissao
    itens = (await db_session.execute(
        select(ItemEmissaoNfe).where(ItemEmissaoNfe.emissao_nfe_id == emissao.id).order_by(ItemEmissaoNfe.id)
    )).scalars().all()
    # Ordem por id (a mesma do worker) preserva a ordem do pedido.
    assert [item.produto_id for item in itens] == [produto_padrao.id, produto_override.id]

    item_padrao, item_override = itens
    assert item_padrao.valor_unitario == Decimal("10.5000")
    assert item_padrao.cfop == "5102"
    assert item_padrao.valor_total == Decimal("31.50")
    assert item_padrao.aliquota_interna_destino is None

    assert item_override.valor_unitario == Decimal("2.3333")
    assert item_override.cfop == "6102"
    # 1.5 * 2.3333 = 3.49995 -> 3.50 (ROUND_HALF_UP, igual ao nfe_builder).
    assert item_override.valor_total == Decimal("3.50")
    assert item_override.aliquota_interna_destino == Decimal("18.00")

    await db_session.refresh(empresa)
    assert empresa.proximo_numero_nfe == 2
    assert empresa.proximo_numero == 1  # numeracao da NFS-e intocada


@pytest.mark.asyncio
async def test_criar_emissao_sem_preco_no_produto_nem_override_e_rejeitado(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    produto_sem_preco = await _criar_produto(db_session, empresa, valor_unitario_padrao=None)

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token,
        json={"cliente_id": str(cliente.id),
              "itens": [{"produto_id": str(produto_sem_preco.id), "quantidade": "1"}]},
    )

    assert resposta.status_code == 422
    assert "valor_unitario" in resposta.json()["detail"]
    await db_session.refresh(empresa)
    assert empresa.proximo_numero_nfe == 1  # numero nao foi consumido


@pytest.mark.asyncio
async def test_criar_emissao_com_produto_inativo_e_rejeitado(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    produto_inativo = await _criar_produto(
        db_session, empresa, valor_unitario_padrao=Decimal("10"), ativo=False,
    )

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token,
        json={"cliente_id": str(cliente.id),
              "itens": [{"produto_id": str(produto_inativo.id), "quantidade": "1"}]},
    )

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_criar_emissao_com_quantidade_zero_e_rejeitado_pelo_schema(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    produto = await _criar_produto(db_session, empresa, valor_unitario_padrao=Decimal("10"))

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token,
        json={"cliente_id": str(cliente.id),
              "itens": [{"produto_id": str(produto.id), "quantidade": "0"}]},
    )

    assert resposta.status_code == 422


@pytest.mark.asyncio
async def test_criar_emissao_sem_itens_e_rejeitado_pelo_schema(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)

    resposta = await _requisitar(
        db_session, "POST", "/api/emissoes-nfe", token,
        json={"cliente_id": str(cliente.id), "itens": []},
    )

    assert resposta.status_code == 422


# --- GET /emissoes-nfe --------------------------------------------------------


@pytest.mark.asyncio
async def test_listar_emissoes_so_da_propria_empresa(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, _token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_a = await _criar_cliente(db_session, empresa_a)
    cliente_b = await _criar_cliente(db_session, empresa_b)
    emissao_a = await _criar_emissao(db_session, empresa_a, cliente_a, numero=7)
    await _criar_emissao(db_session, empresa_b, cliente_b, numero=8)
    produto_a = await _criar_produto(db_session, empresa_a)
    db_session.add(ItemEmissaoNfe(
        emissao_nfe_id=emissao_a.id, produto_id=produto_a.id, quantidade=Decimal("2"),
        valor_unitario=Decimal("5"), valor_total=Decimal("10"), cfop="5102",
    ))
    await db_session.commit()

    resposta = await _requisitar(db_session, "GET", "/api/emissoes-nfe", token_a)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [e["numero"] for e in corpo] == [7]
    assert len(corpo[0]["itens"]) == 1
    assert corpo[0]["itens"][0]["cfop"] == "5102"


# --- GET /emissoes-nfe/{id}/xml -----------------------------------------------


@pytest.mark.asyncio
async def test_baixar_xml_devolve_o_xml_gravado(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    # Rejeitada de proposito: o XML vale como evidencia mesmo sem autorizacao.
    emissao = await _criar_emissao(
        db_session, empresa, cliente, status=StatusEmissao.rejeitada, xml_nfe=b"<NFe>ok</NFe>",
    )

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao.id}/xml", token)

    assert resposta.status_code == 200
    assert resposta.content == b"<NFe>ok</NFe>"
    assert resposta.headers["content-type"].startswith("application/xml")
    assert "NFe_1_1.xml" in resposta.headers["content-disposition"]


@pytest.mark.asyncio
async def test_baixar_xml_ainda_nao_montado_devolve_404(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente)

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao.id}/xml", token)

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_baixar_xml_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    _empresa_b, token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_a = await _criar_cliente(db_session, empresa_a)
    emissao_a = await _criar_emissao(db_session, empresa_a, cliente_a, xml_nfe=b"<NFe/>")

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao_a.id}/xml", token_b)

    assert resposta.status_code == 404


# --- GET /emissoes-nfe/{id}/pdf -----------------------------------------------


@pytest.mark.asyncio
async def test_baixar_pdf_de_emissao_autorizada_gera_danfe(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    produto = await _criar_produto(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente, status=StatusEmissao.autorizada)
    db_session.add(ItemEmissaoNfe(
        emissao_nfe_id=emissao.id, produto_id=produto.id, quantidade=Decimal("2"),
        valor_unitario=Decimal("5"), valor_total=Decimal("10"), cfop="5102",
    ))
    await db_session.commit()

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao.id}/pdf", token)

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/pdf"
    assert resposta.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_baixar_pdf_de_emissao_nao_autorizada_devolve_404(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = await _criar_cliente(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente, status=StatusEmissao.rejeitada)

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao.id}/pdf", token)

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_baixar_pdf_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    _empresa_b, token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_a = await _criar_cliente(db_session, empresa_a)
    emissao_a = await _criar_emissao(db_session, empresa_a, cliente_a, status=StatusEmissao.autorizada)

    resposta = await _requisitar(db_session, "GET", f"/api/emissoes-nfe/{emissao_a.id}/pdf", token_b)

    assert resposta.status_code == 404


# --- POST /emissoes-nfe/{id}/cancelar -----------------------------------------


@pytest.mark.asyncio
async def test_cancelar_emissao_nao_autorizada_e_rejeitado(db_session):
    empresa, token = await criar_empresa_e_token(db_session, papel=PapelUsuario.admin)
    cliente = await _criar_cliente(db_session, empresa)
    emissao_pendente = await _criar_emissao(db_session, empresa, cliente)

    resposta = await _requisitar(
        db_session, "POST", f"/api/emissoes-nfe/{emissao_pendente.id}/cancelar", token,
        json={"justificativa": "Erro no pedido do cliente"},
    )

    # 409 (estado errado pra operacao), mesma convencao do cancelar da NFS-e.
    assert resposta.status_code == 409
    await db_session.refresh(emissao_pendente)
    assert emissao_pendente.status == StatusEmissao.aguardando_emissao


@pytest.mark.asyncio
async def test_cancelar_emissao_autorizada_fica_pendente_e_grava_justificativa(db_session):
    empresa, token = await criar_empresa_e_token(db_session, papel=PapelUsuario.admin)
    cliente = await _criar_cliente(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente, status=StatusEmissao.autorizada)

    resposta = await _requisitar(
        db_session, "POST", f"/api/emissoes-nfe/{emissao.id}/cancelar", token,
        json={"justificativa": "  Erro no pedido do cliente  "},
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["status"] == "cancelamento_pendente"
    assert corpo["justificativa_cancelamento"] == "Erro no pedido do cliente"
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_pendente
    assert emissao.justificativa_cancelamento == "Erro no pedido do cliente"


@pytest.mark.asyncio
async def test_cancelar_com_justificativa_curta_e_rejeitado_pelo_schema(db_session):
    empresa, token = await criar_empresa_e_token(db_session, papel=PapelUsuario.admin)
    cliente = await _criar_cliente(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente, status=StatusEmissao.autorizada)

    # 14 caracteres depois do strip (o minimo do xJust e 15, ver nfe_core.evento).
    resposta = await _requisitar(
        db_session, "POST", f"/api/emissoes-nfe/{emissao.id}/cancelar", token,
        json={"justificativa": "   Erro no pedid   "},
    )

    assert resposta.status_code == 422
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada


@pytest.mark.asyncio
async def test_cancelar_exige_admin_da_empresa(db_session):
    empresa, token_operador = await criar_empresa_e_token(db_session, papel=PapelUsuario.operador)
    cliente = await _criar_cliente(db_session, empresa)
    emissao = await _criar_emissao(db_session, empresa, cliente, status=StatusEmissao.autorizada)

    resposta = await _requisitar(
        db_session, "POST", f"/api/emissoes-nfe/{emissao.id}/cancelar", token_operador,
        json={"justificativa": "Erro no pedido do cliente"},
    )

    assert resposta.status_code == 403


@pytest.mark.asyncio
async def test_cancelar_emissao_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    _empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="22222222000122", email="b@teste.com", papel=PapelUsuario.admin,
    )
    cliente_a = await _criar_cliente(db_session, empresa_a)
    emissao_a = await _criar_emissao(db_session, empresa_a, cliente_a, status=StatusEmissao.autorizada)

    resposta = await _requisitar(
        db_session, "POST", f"/api/emissoes-nfe/{emissao_a.id}/cancelar", token_b,
        json={"justificativa": "Erro no pedido do cliente"},
    )

    assert resposta.status_code == 404
