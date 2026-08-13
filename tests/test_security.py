import uuid

import pytest
from fastapi import HTTPException
from jose import jwt

from app.config import get_settings
from app.crypto import hash_senha
from app.models import PapelUsuario, Usuario
from app.security import (
    criar_token,
    exigir_admin_empresa,
    exigir_admin_plataforma,
    get_contexto_autenticado,
    get_empresa_ativa,
)


async def _usuario(db_session, **overrides) -> Usuario:
    dados = dict(email="u@teste.com", senha_hash=hash_senha("senha-forte-123"))
    dados.update(overrides)
    usuario = Usuario(**dados)
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


def test_criar_token_sem_empresa_ativa_grava_campos_nulos():
    usuario = Usuario(
        id=uuid.uuid4(), email="x@x.com", senha_hash="hash", eh_admin_plataforma=False,
    )
    token = criar_token(usuario)
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["empresa_id"] is None
    assert payload["papel"] is None
    assert payload["eh_admin_plataforma"] is False


def test_criar_token_com_empresa_ativa_grava_empresa_id_e_papel():
    usuario = Usuario(
        id=uuid.uuid4(), email="x@x.com", senha_hash="hash", eh_admin_plataforma=False,
    )
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.admin)
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    assert payload["empresa_id"] == str(empresa_id)
    assert payload["papel"] == "admin"


@pytest.mark.asyncio
async def test_get_contexto_autenticado_resolve_usuario_e_campos_do_token(db_session):
    usuario = await _usuario(db_session)
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.operador)

    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    assert contexto.usuario.id == usuario.id
    assert contexto.empresa_id == empresa_id
    assert contexto.papel == PapelUsuario.operador
    assert contexto.eh_admin_plataforma is False


@pytest.mark.asyncio
async def test_get_empresa_ativa_rejeita_contexto_sem_empresa(db_session):
    usuario = await _usuario(db_session, email="sem-empresa@teste.com")
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await get_empresa_ativa(contexto=contexto)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_exigir_admin_empresa_rejeita_operador(db_session):
    usuario = await _usuario(db_session, email="operador@teste.com")
    empresa_id = uuid.uuid4()
    token = criar_token(usuario, empresa_id=empresa_id, papel=PapelUsuario.operador)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await exigir_admin_empresa(contexto=contexto)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_exigir_admin_plataforma_rejeita_quem_nao_e(db_session):
    usuario = await _usuario(db_session, email="comum@teste.com")
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    with pytest.raises(HTTPException) as exc:
        await exigir_admin_plataforma(contexto=contexto)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_exigir_admin_plataforma_aceita_admin_de_plataforma(db_session):
    usuario = await _usuario(db_session, email="adm@teste.com", eh_admin_plataforma=True)
    token = criar_token(usuario)
    contexto = await get_contexto_autenticado(
        token=token, session=db_session, settings=get_settings()
    )

    resultado = await exigir_admin_plataforma(contexto=contexto)
    assert resultado.eh_admin_plataforma is True
