"""nbs code em empresas

Revision ID: d5f2b8e4c6a1
Revises: c3e7a1f9b2d4
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f2b8e4c6a1'
down_revision: Union[str, Sequence[str], None] = 'c3e7a1f9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('nbs_code', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'nbs_code')
