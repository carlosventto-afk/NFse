"""resposta_bruta em emissoes

Revision ID: 4b7e1a9c3d2f
Revises: 8a4d2f6e9b1c
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b7e1a9c3d2f'
down_revision: Union[str, Sequence[str], None] = '8a4d2f6e9b1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('resposta_bruta', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'resposta_bruta')
