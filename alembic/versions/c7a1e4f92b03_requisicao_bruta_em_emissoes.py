"""requisicao bruta em emissoes

Revision ID: c7a1e4f92b03
Revises: b3f9d2c8a1e6
Create Date: 2026-09-21 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a1e4f92b03'
down_revision: Union[str, Sequence[str], None] = 'b3f9d2c8a1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('requisicao_bruta', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'requisicao_bruta')
