"""data vencimento em emissoes

Revision ID: d4f6b8e21a97
Revises: c7a1e4f92b03
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f6b8e21a97'
down_revision: Union[str, Sequence[str], None] = 'c7a1e4f92b03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('data_vencimento', sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'data_vencimento')
