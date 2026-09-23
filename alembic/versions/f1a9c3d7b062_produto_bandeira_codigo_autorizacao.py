"""produto bandeira codigo autorizacao em emissoes

Revision ID: f1a9c3d7b062
Revises: d4f6b8e21a97
Create Date: 2026-09-23 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a9c3d7b062'
down_revision: Union[str, Sequence[str], None] = 'd4f6b8e21a97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('produto', sa.String(length=30), nullable=True))
    op.add_column('emissoes', sa.Column('tipo_produto', sa.String(length=20), nullable=True))
    op.add_column('emissoes', sa.Column('bandeira', sa.String(length=30), nullable=True))
    op.add_column('emissoes', sa.Column('codigo_autorizacao', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'codigo_autorizacao')
    op.drop_column('emissoes', 'bandeira')
    op.drop_column('emissoes', 'tipo_produto')
    op.drop_column('emissoes', 'produto')
