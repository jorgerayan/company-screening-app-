"""Add findings table

Revision ID: 002
Revises: 001
Create Date: 2025-01-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.id"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=True,
        ),
        sa.Column("field_name", sa.String(200), nullable=False),
        sa.Column("field_value", sa.String(2000), nullable=False),
        sa.Column(
            "evidence_type",
            sa.Enum(
                "verified_fact",
                "reasonable_inference",
                "unverifiable",
                name="evidencetype",
            ),
            nullable=False,
            server_default="unverifiable",
        ),
        sa.Column(
            "confidence",
            sa.Enum("high", "medium", "low", name="confidencelevel"),
            nullable=False,
            server_default="low",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_findings_analysis_id", "findings", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_analysis_id", table_name="findings")
    op.drop_table("findings")
    op.execute("DROP TYPE IF EXISTS evidencetype")
    op.execute("DROP TYPE IF EXISTS confidencelevel")
