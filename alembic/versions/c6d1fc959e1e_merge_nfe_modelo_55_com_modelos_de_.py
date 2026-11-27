"""merge nfe modelo 55 com modelos de descricao

Revision ID: c6d1fc959e1e
Revises: 443523d6a51e, b7881c92c4e4
Create Date: 2026-11-27 11:24:17.299747

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6d1fc959e1e'
down_revision: Union[str, Sequence[str], None] = ('443523d6a51e', 'b7881c92c4e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
