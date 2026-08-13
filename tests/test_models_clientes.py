from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AmbienteEnum, Cliente, Emissao, Empresa, OrigemEmissao, StatusEmissao
from tests.apoio import criar_empresa_titular


async def _empresa(db_session) -> Empresa:
    empresa, _titular = await criar_empresa_titular(db_session)
    return empresa


@pytest.mark.asyncio
async def test_cliente_grava_todos_os_campos_fiscais(db_session):
    empresa = await _empresa(db_session)

    cliente = Cliente(
        empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Cliente Teste",
        email="cliente@teste.com", telefone="11999999999",
        inscricao_estadual="ISENTO", inscricao_municipal="123456",
        logradouro="Rua das Flores", numero="100", complemento="Ap 1",
        bairro="Centro", municipio_ibge="3550308", uf="SP", cep="01001000",
    )
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)

    assert cliente.ativo is True
    assert cliente.eh_padrao_csv is False
    assert cliente.cep == "01001000"


@pytest.mark.asyncio
async def test_cliente_permite_multiplos_com_cpf_cnpj_nulo_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)

    db_session.add(Cliente(empresa_id=empresa.id, nome="Sem documento 1"))
    db_session.add(Cliente(empresa_id=empresa.id, nome="Sem documento 2"))
    await db_session.commit()  # nao deve levantar


@pytest.mark.asyncio
async def test_cliente_rejeita_cpf_cnpj_duplicado_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Um"))
    await db_session.commit()

    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Outro"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_cliente_rejeita_segundo_padrao_csv_na_mesma_empresa(db_session):
    empresa = await _empresa(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, nome="Padrao 1", eh_padrao_csv=True))
    await db_session.commit()

    db_session.add(Cliente(empresa_id=empresa.id, nome="Padrao 2", eh_padrao_csv=True))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_emissao_aceita_cliente_id_opcional(db_session):
    empresa = await _empresa(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Vinculado")
    db_session.add(cliente)
    await db_session.flush()

    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor="10.00", competencia=datetime(2026, 8, 1).date(),
        cliente_id=cliente.id,
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)

    assert emissao.cliente_id == cliente.id
