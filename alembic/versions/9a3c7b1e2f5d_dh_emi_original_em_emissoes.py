"""dh_emi_original em emissoes

Revision ID: 9a3c7b1e2f5d
Revises: 6fc65ec86b40
Create Date: 2026-08-17 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3c7b1e2f5d'
down_revision: Union[str, Sequence[str], None] = '6fc65ec86b40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('dh_emi_original', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'dh_emi_original')
