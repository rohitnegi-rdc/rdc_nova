"""Add push_subscription table

Revision ID: 4332e9da9c6a
Revises: 461111b60977
Create Date: 2026-09-17 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = '4332e9da9c6a'
down_revision = '461111b60977'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'push_subscription' not in inspector.get_table_names():
        op.create_table(
            'push_subscription',
            sa.Column('id', sa.Text(), nullable=False),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('endpoint', sa.Text(), nullable=False),
            sa.Column('p256dh', sa.Text(), nullable=False),
            sa.Column('auth', sa.Text(), nullable=False),
            sa.Column('user_agent', sa.Text(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=True),
            sa.Column('last_used_at', sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('endpoint'),
        )
        op.create_index('ix_push_subscription_user_id', 'push_subscription', ['user_id'])


def downgrade():
    op.drop_index('ix_push_subscription_user_id', table_name='push_subscription')
    op.drop_table('push_subscription')
