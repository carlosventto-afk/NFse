"""cnae em empresas

Revision ID: b3f9d2c8a1e6
Revises: a5d9f13c6e82
Create Date: 2026-09-17 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f9d2c8a1e6'
down_revision: Union[str, Sequence[str], None] = 'a5d9f13c6e82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('cnae', sa.String(length=10), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'cnae')
