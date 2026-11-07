"""modelos descricao

Revision ID: b7881c92c4e4
Revises: e6a4c1f8d2b7
Create Date: 2026-11-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7881c92c4e4'
down_revision: Union[str, Sequence[str], None] = 'e6a4c1f8d2b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'modelos_descricao',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('empresa_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cliente_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('titulo', sa.String(length=80), nullable=False),
        sa.Column('texto', sa.String(length=2000), nullable=False),
        sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('modelos_descricao')
