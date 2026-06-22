"""fix_delivery_status_and_users_fk

Revision ID: d5c82e600657
Revises: c59ba6c5ad9d
Create Date: 2026-06-22 15:23:53.659075

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5c82e600657'
down_revision: Union[str, None] = 'c59ba6c5ad9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_users_tenant_id', 'tenants', ['tenant_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_tenant_id', type_='foreignkey')
