"""provedor de emissao e integracao com a Spedy

Revision ID: a5d9f13c6e82
Revises: 4b7e1a9c3d2f
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5d9f13c6e82'
down_revision: Union[str, Sequence[str], None] = '4b7e1a9c3d2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('razao_social', sa.String(length=200), nullable=True))
    op.add_column('empresas', sa.Column('logradouro', sa.String(length=200), nullable=True))
    op.add_column('empresas', sa.Column('numero', sa.String(length=20), nullable=True))
    op.add_column('empresas', sa.Column('complemento', sa.String(length=100), nullable=True))
    op.add_column('empresas', sa.Column('bairro', sa.String(length=100), nullable=True))
    op.add_column('empresas', sa.Column('cep', sa.String(length=8), nullable=True))
    op.add_column(
        'empresas',
        sa.Column('provedor_emissao', sa.String(length=20), nullable=False, server_default='direto'),
    )
    op.add_column('empresas', sa.Column('spedy_empresa_id', sa.String(length=36), nullable=True))
    op.add_column('empresas', sa.Column('spedy_api_key_cifrada', sa.Text(), nullable=True))
    op.add_column('emissoes', sa.Column('spedy_nota_id', sa.String(length=36), nullable=True))
    op.alter_column('emissoes', 'status', existing_type=sa.String(length=30), type_=sa.String(length=40))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('emissoes', 'status', existing_type=sa.String(length=40), type_=sa.String(length=30))
    op.drop_column('emissoes', 'spedy_nota_id')
    op.drop_column('empresas', 'spedy_api_key_cifrada')
    op.drop_column('empresas', 'spedy_empresa_id')
    op.drop_column('empresas', 'provedor_emissao')
    op.drop_column('empresas', 'cep')
    op.drop_column('empresas', 'bairro')
    op.drop_column('empresas', 'complemento')
    op.drop_column('empresas', 'numero')
    op.drop_column('empresas', 'logradouro')
    op.drop_column('empresas', 'razao_social')
