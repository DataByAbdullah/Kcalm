"""Nullable user avatar Data URLs.

Revision ID: 20261118_0024
Revises: 20261110_0023
"""
from alembic import op
import sqlalchemy as sa


revision = "20261118_0024"
down_revision = "20261110_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_data_url", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("users", "avatar_data_url")
