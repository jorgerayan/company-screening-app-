"""Add management, competitive_position, operational_signals, corporate_structure to reports

Revision ID: 004
Revises: 003
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("management", JSONB, nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("competitive_position", JSONB, nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("operational_signals", JSONB, nullable=True),
    )
    op.add_column(
        "reports",
        sa.Column("corporate_structure", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reports", "corporate_structure")
    op.drop_column("reports", "operational_signals")
    op.drop_column("reports", "competitive_position")
    op.drop_column("reports", "management")
