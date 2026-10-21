"""Revoke existing sessions on password changes."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0017"
down_revision = "20261021_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("users", "token_version")
