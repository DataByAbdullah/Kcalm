"""Durable recipe images and recoverable generation claims.

Revision ID: 20261110_0023
Revises: 20261105_0022
"""
from alembic import op
import sqlalchemy as sa


revision = "20261110_0023"
down_revision = "20261105_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recipes", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("image_storage_key", sa.String(512), nullable=True))
    op.add_column("recipes", sa.Column("image_status", sa.String(16), nullable=False, server_default="missing"))
    op.add_column("recipes", sa.Column("image_prompt", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("image_model", sa.String(128), nullable=True))
    op.add_column("recipes", sa.Column("image_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recipes", sa.Column("image_error", sa.Text(), nullable=True))
    op.add_column("recipes", sa.Column("image_generation_token", sa.Uuid(), nullable=True))
    op.add_column("recipes", sa.Column("image_generation_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_recipes_image_status_valid", "recipes",
        "image_status in ('missing', 'generating', 'ready', 'failed')",
    )


def downgrade():
    op.drop_constraint("ck_recipes_image_status_valid", "recipes", type_="check")
    for column in (
        "image_generation_started_at", "image_generation_token", "image_error", "image_generated_at",
        "image_model", "image_prompt", "image_status", "image_storage_key", "image_url",
    ):
        op.drop_column("recipes", column)
