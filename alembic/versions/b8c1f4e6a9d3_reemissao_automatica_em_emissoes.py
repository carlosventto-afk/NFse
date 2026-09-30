"""reemissao automatica em emissoes

Revision ID: b8c1f4e6a9d3
Revises: a7d3e9c2f4b1
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c1f4e6a9d3'
down_revision: Union[str, Sequence[str], None] = 'a7d3e9c2f4b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('emissoes', sa.Column('tentativas_reemissao', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('emissoes', sa.Column('proxima_tentativa_em', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('emissoes', 'proxima_tentativa_em')
    op.drop_column('emissoes', 'tentativas_reemissao')
