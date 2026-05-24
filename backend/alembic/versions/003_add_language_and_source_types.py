"""Add language to companies and new source types

Revision ID: 003
Revises: 002
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add language column to companies (default: 'es')
    op.add_column(
        "companies",
        sa.Column("language", sa.String(10), nullable=True, server_default="es"),
    )

    # Extend the sourcetype PostgreSQL enum with new values
    # IF NOT EXISTS requires PostgreSQL 9.3+ — safe for all modern versions
    new_source_types = [
        "google_news",
        "wikipedia",
        "app_stores",
        "github",
        "similarweb",
        "glassdoor",
    ]
    for value in new_source_types:
        op.execute(f"ALTER TYPE sourcetype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.drop_column("companies", "language")
    # NOTE: PostgreSQL does not support removing enum values.
    # Source type values added in upgrade() cannot be rolled back automatically.
