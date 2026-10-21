"""Reviewed food allergens; null explicitly means unknown."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0018"
down_revision = "20261021_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("foods", sa.Column("allergen_codes", sa.JSON(), nullable=True))
    op.add_column("foods", sa.Column("allergen_reference", sa.String(1000), nullable=True))


def downgrade():
    op.drop_column("foods", "allergen_reference")
    op.drop_column("foods", "allergen_codes")
