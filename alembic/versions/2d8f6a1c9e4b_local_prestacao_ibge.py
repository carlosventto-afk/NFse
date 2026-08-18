"""local_prestacao_ibge em empresas

Revision ID: 2d8f6a1c9e4b
Revises: 7c1e4a9d3b6f
Create Date: 2026-08-18 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d8f6a1c9e4b'
down_revision: Union[str, Sequence[str], None] = '7c1e4a9d3b6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('local_prestacao_ibge', sa.String(length=7), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'local_prestacao_ibge')
