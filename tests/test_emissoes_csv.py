import io
from datetime import datetime
from decimal import Decimal

import functools

import openpyxl
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.periodo import FUSO_BRT
from tests.apoio import criar_empresa_e_token

CABECALHO = (
    "DOCUMENTO", "STONECODE", "DATA DA VENDA", "BANDEIRA", "PRODUTO", "STONE ID",
    "N DE PARCELAS", "VALOR BRUTO", "ULTIMO STATUS", "DATA DO ULTIMO STATUS",
    "CODIGO DE AUTORIZACAO",
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


def _arquivo(conteudo: bytes, nome: str = "vendas.xlsx"):
    return {
        "arquivo": (
            nome, conteudo,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }


async def _yield_session(session):
    yield session


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    return await criar_empresa_e_token(
        db_session, municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa",
    )


@pytest.mark.asyncio
async def test_preview_xlsx_nao_grava_nada_e_devolve_resumo_correto(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
        ("49055093000140", "477557478", "30/07/2026 17:00", "Elo", "Debito", "31163341016913",
         "1", "13,990000", "Aprovada", "30/07/2026 17:00", "AB124"),
        ("49055093000140", "477557478", "30/07/2026 10:00", "Visa", "Credito", "31163300000001",
         "1", "5,000000", "Negada", "30/07/2026 10:00", ""),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/preview", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
        assert corpo["ignoradas"] == {
            "status_nao_aprovado": 1, "linha_invalida": 0, "ja_emitida_anteriormente": 0,
        }
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []
    await db_session.refresh(empresa)
    assert empresa.proximo_numero == 1


@pytest.mark.asyncio
async def test_confirmar_xlsx_cria_emissoes_com_todos_os_campos_da_stone(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "05/08/2026 09:15", "AB123"),
        ("49055093000140", "", "30/07/2026 17:00", "", "Pix QRcode", "E20855875202608010010JR",
         "", "13,990000", "Aprovada", "06/08/2026 11:20", ""),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
    finally:
        app.dependency_overrides.clear()

    emissoes = (
        await db_session.execute(
            select(Emissao).where(Emissao.empresa_id == empresa.id).order_by(Emissao.numero)
        )
    ).scalars().all()
    assert len(emissoes) == 2
    assert [e.numero for e in emissoes] == [1, 2]
    assert {e.origem for e in emissoes} == {OrigemEmissao.csv}
    assert {e.status for e in emissoes} == {StatusEmissao.aguardando_emissao}
    assert {e.stone_charge_id for e in emissoes} == {"31163337249888", "E20855875202608010010JR"}
    # descricao leva a data da venda junto (nao ha mais "vencimento" separado
    # nesse relatorio), alem do texto padrao da empresa
    assert {e.descricao for e in emissoes} == {
        "Lavagem de roupa - Venda: 30/07/2026",
    }
    assert {e.valor for e in emissoes} == {Decimal("27.98"), Decimal("13.99")}
    # competencia e data_vencimento vem da DATA DA VENDA (nao existe mais
    # DATA DE VENCIMENTO nesse relatorio de vendas)
    assert {e.competencia.isoformat() for e in emissoes} == {"2026-07-01"}
    assert {e.data_vencimento.isoformat() for e in emissoes} == {"2026-07-30"}

    cartao = next(e for e in emissoes if e.stone_charge_id == "31163337249888")
    assert cartao.produto == "Credito"
    assert cartao.tipo_produto == "Credito"
    assert cartao.bandeira == "Visa"
    assert cartao.codigo_autorizacao == "AB123"

    pix = next(e for e in emissoes if e.stone_charge_id == "E20855875202608010010JR")
    assert pix.produto == "Pix QRcode"
    assert pix.tipo_produto == "PIX"
    assert pix.bandeira is None
    assert pix.codigo_autorizacao is None

    # dh_emi_original vem da coluna DATA DO ULTIMO STATUS (pagamento real,
    # nao a data em que a importacao rodou) — permite competencia retroativa.
    assert {e.dh_emi_original.astimezone(FUSO_BRT).replace(tzinfo=None) for e in emissoes} == {
        datetime(2026, 8, 5, 9, 15, 0), datetime(2026, 8, 6, 11, 20, 0),
    }


@pytest.mark.asyncio
async def test_confirmar_xlsx_duas_vezes_nao_duplica_nem_reserva_numero_de_novo(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )
            segunda = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert primeira.json()["total_notas"] == 1
        assert segunda.json()["total_notas"] == 0
        assert segunda.json()["ignoradas"]["ja_emitida_anteriormente"] == 1
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "31163337249888"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_confirmar_xlsx_nao_cruza_dedupe_nem_visibilidade_entre_empresas(db_session):
    empresa_a, token_a = await _empresa_e_usuario(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-b@teste.com",
        municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa B",
    )

    # mesmo STONE ID em ambas as empresas — nao deveria haver colisao de dedupe
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta_a = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token_a}"},
            )
            resposta_b = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert resposta_a.json()["total_notas"] == 1
        # empresa B nao e afetada pelo STONE ID ja usado pela empresa A
        assert resposta_b.json()["total_notas"] == 1
        assert resposta_b.json()["ignoradas"]["ja_emitida_anteriormente"] == 0
    finally:
        app.dependency_overrides.clear()

    emissoes_b = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa_b.id))
    ).scalars().all()
    assert len(emissoes_b) == 1
    assert emissoes_b[0].descricao == "Lavagem de roupa B - Venda: 30/07/2026"


@pytest.mark.asyncio
async def test_xlsx_com_cabecalho_invalido_devolve_400_sem_gravar_nada(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    planilha = openpyxl.Workbook()
    aba = planilha.active
    aba.append(("COLUNA_ERRADA", "OUTRA"))
    aba.append(("x", "y"))
    buffer = io.BytesIO()
    planilha.save(buffer)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(buffer.getvalue()),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []


@pytest.mark.asyncio
async def test_confirmar_xlsx_vincula_cliente_padrao_e_reutiliza_entre_importacoes(db_session):
    from app.models import Cliente

    empresa, token = await _empresa_e_usuario(db_session)
    primeira = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
    )
    segunda = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 15:00", "Visa", "Credito", "31163337249999",
         "1", "15,000000", "Aprovada", "30/07/2026 15:00", "AB124"),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(primeira, "relatorio1.xlsx"),
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(segunda, "relatorio2.xlsx"),
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    clientes_padrao = (
        await db_session.execute(
            select(Cliente).where(Cliente.empresa_id == empresa.id, Cliente.eh_padrao_csv.is_(True))
        )
    ).scalars().all()
    assert len(clientes_padrao) == 1

    emissoes = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert len(emissoes) == 2
    assert {e.cliente_id for e in emissoes} == {clientes_padrao[0].id}


@pytest.mark.asyncio
async def test_listar_emissoes_filtra_por_data_de_vencimento(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _xlsx(
        ("49055093000140", "477557478", "29/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "29/07/2026 14:30", "AB123"),
        ("49055093000140", "477557478", "30/07/2026 17:00", "Elo", "Debito", "31163341016913",
         "1", "13,990000", "Aprovada", "30/07/2026 17:00", "AB124"),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )
            resposta = await client.get(
                "/api/emissoes",
                params={"vencimento_inicio": "2026-07-30", "vencimento_fim": "2026-07-30"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert len(corpo) == 1
        assert corpo[0]["data_vencimento"] == "2026-07-30"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_emissoes_filtra_por_produto_tipo_produto_e_bandeira(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _xlsx(
        ("49055093000140", "477557478", "30/07/2026 14:30", "Visa", "Credito", "31163337249888",
         "1", "27,980000", "Aprovada", "30/07/2026 14:30", "AB123"),
        ("49055093000140", "477557478", "30/07/2026 15:00", "MasterCard", "Debito Pre-pago", "31163337249901",
         "1", "13,990000", "Aprovada", "30/07/2026 15:00", "AB125"),
        ("49055093000140", "", "30/07/2026 16:00", "", "Pix QRcode", "E20855875202608010010JR",
         "", "13,990000", "Aprovada", "30/07/2026 16:00", ""),
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/emissoes/csv/confirmar", files=_arquivo(conteudo),
                headers={"Authorization": f"Bearer {token}"},
            )

            por_tipo = await client.get(
                "/api/emissoes", params={"tipo_produto": "Debito"},
                headers={"Authorization": f"Bearer {token}"},
            )
            por_bandeira = await client.get(
                "/api/emissoes", params={"bandeira": "Visa"},
                headers={"Authorization": f"Bearer {token}"},
            )
            por_produto = await client.get(
                "/api/emissoes", params={"produto": "Pix QRcode"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert len(por_tipo.json()) == 1
        assert por_tipo.json()[0]["produto"] == "Debito Pre-pago"
        assert len(por_bandeira.json()) == 1
        assert por_bandeira.json()[0]["bandeira"] == "Visa"
        assert len(por_produto.json()) == 1
        assert por_produto.json()[0]["tipo_produto"] == "PIX"
    finally:
        app.dependency_overrides.clear()
