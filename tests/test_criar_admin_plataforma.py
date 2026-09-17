import pytest
from sqlalchemy import select

from app.crypto import verificar_senha
from app.models import Usuario
from scripts.criar_admin_plataforma import criar_ou_promover_admin_plataforma


@pytest.mark.asyncio
async def test_cria_novo_admin_plataforma(db_session):
    usuario = await criar_ou_promover_admin_plataforma(
        db_session, "novo-admin@teste.com", "senha-do-admin",
    )

    assert usuario.eh_admin_plataforma is True
    assert verificar_senha("senha-do-admin", usuario.senha_hash)

    do_banco = (
        await db_session.execute(select(Usuario).where(Usuario.email == "novo-admin@teste.com"))
    ).scalar_one()
    assert do_banco.eh_admin_plataforma is True


@pytest.mark.asyncio
async def test_promove_usuario_existente_a_admin_plataforma(db_session):
    from app.crypto import hash_senha

    usuario_comum = Usuario(email="ja-existe@teste.com", senha_hash=hash_senha("senha-antiga"))
    db_session.add(usuario_comum)
    await db_session.commit()

    promovido = await criar_ou_promover_admin_plataforma(
        db_session, "ja-existe@teste.com", "senha-nova",
    )

    assert promovido.id == usuario_comum.id
    assert promovido.eh_admin_plataforma is True
    assert verificar_senha("senha-nova", promovido.senha_hash)
    assert not verificar_senha("senha-antiga", promovido.senha_hash)
