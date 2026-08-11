import functools
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario
from app.security import criar_token


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return empresa, criar_token(usuario)


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_emissao_manual_reserva_numero_e_cria_pendente(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    # FastAPI so reconhece uma dependencia como "async generator" olhando para
    # a funcao geradora em si (via functools.partial ela continua visivel
    # atraves do unwrap); uma lambda que apenas retorna o generator ja
    # instanciado nao e reconhecida e quebra a injecao de sessao.
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "cpf_cnpj": "98765432100", "nome": "Cliente Manual",
                    "descricao": "Lavagem de edredom", "valor": "35.00",
                    "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["origem"] == "manual"
        assert corpo["status"] == "pendente"
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] == "98765432100"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_com_cpf_invalido_nao_reserva_numero(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "cpf_cnpj": "123", "nome": "Cliente Invalido",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422

        await db_session.refresh(empresa)
        assert empresa.proximo_numero == 1  # nao avancou
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_sem_documento_do_tomador_e_aceita(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/manual",
                json={
                    "nome": "Cliente Sem Documento",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] is None
    finally:
        app.dependency_overrides.clear()
