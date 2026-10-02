"""ambiente em emissoes

Revision ID: c3e7a1f9b2d4
Revises: b8c1f4e6a9d3
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e7a1f9b2d4'
down_revision: Union[str, Sequence[str], None] = 'b8c1f4e6a9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('ambiente', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'ambiente')
