"""codigo_tributacao_municipal em empresas

Revision ID: 6f2b8c4a1d7e
Revises: 2d8f6a1c9e4b
Create Date: 2026-08-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f2b8c4a1d7e'
down_revision: Union[str, Sequence[str], None] = '2d8f6a1c9e4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('codigo_tributacao_municipal', sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'codigo_tributacao_municipal')
