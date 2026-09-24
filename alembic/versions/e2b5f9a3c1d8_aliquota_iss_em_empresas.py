"""aliquota iss em empresas

Revision ID: e2b5f9a3c1d8
Revises: f1a9c3d7b062
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b5f9a3c1d8'
down_revision: Union[str, Sequence[str], None] = 'f1a9c3d7b062'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('empresas', sa.Column('aliquota_iss', sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('empresas', 'aliquota_iss')
