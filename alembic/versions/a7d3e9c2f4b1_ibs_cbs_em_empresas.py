"""ibs cbs em empresas

Revision ID: a7d3e9c2f4b1
Revises: e2b5f9a3c1d8
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3e9c2f4b1'
down_revision: Union[str, Sequence[str], None] = 'e2b5f9a3c1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('ibs_cbs_cst', sa.Integer(), nullable=True))
    op.add_column('empresas', sa.Column('ibs_cbs_classificacao', sa.Integer(), nullable=True))
    op.add_column('empresas', sa.Column('ibs_cbs_codigo_indicador_operacao', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'ibs_cbs_codigo_indicador_operacao')
    op.drop_column('empresas', 'ibs_cbs_classificacao')
    op.drop_column('empresas', 'ibs_cbs_cst')
