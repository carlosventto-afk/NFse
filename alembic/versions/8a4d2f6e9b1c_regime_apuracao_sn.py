"""regime_apuracao_sn em empresas

Revision ID: 8a4d2f6e9b1c
Revises: 6f2b8c4a1d7e
Create Date: 2026-08-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a4d2f6e9b1c'
down_revision: Union[str, Sequence[str], None] = '6f2b8c4a1d7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('regime_apuracao_sn', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'regime_apuracao_sn')
