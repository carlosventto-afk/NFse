"""inscricao_municipal opcional em empresas

Revision ID: 7c1e4a9d3b6f
Revises: 9a3c7b1e2f5d
Create Date: 2026-08-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4a9d3b6f'
down_revision: Union[str, Sequence[str], None] = '9a3c7b1e2f5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('empresas', 'inscricao_municipal', existing_type=sa.String(length=20), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('empresas', 'inscricao_municipal', existing_type=sa.String(length=20), nullable=False)
