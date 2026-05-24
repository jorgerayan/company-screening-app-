"""Initial schema

Revision ID: 001
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("website_url", sa.String(500), nullable=False),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("sector_hint", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_companies_name", "companies", ["name"])

    op.create_table(
        "analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("status", sa.Enum("pending","running","completed","failed", name="analysisstatus"), nullable=False, server_default="pending"),
        sa.Column("pipeline_step", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("source_type", sa.Enum("website","opencorporates","borme","gdelt","crossref","other", name="sourcetype"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.Enum("ok","failed","partial", name="sourcestatus"), nullable=False, server_default="ok"),
        sa.Column("raw_content", sa.Text, nullable=True),
    )

    op.create_table(
        "llm_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("module_name", sa.String(100), nullable=False),
        sa.Column("input_payload", postgresql.JSONB, nullable=False),
        sa.Column("output_payload", postgresql.JSONB, nullable=False),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analyses.id"), unique=True, nullable=False),
        sa.Column("factual_profile", postgresql.JSONB, nullable=False),
        sa.Column("business_model", postgresql.JSONB, nullable=False),
        sa.Column("traction_signals", postgresql.JSONB, nullable=False),
        sa.Column("risks", postgresql.JSONB, nullable=False),
        sa.Column("references", postgresql.JSONB, nullable=False),
        sa.Column("conclusion", postgresql.JSONB, nullable=False),
        sa.Column("priority_rating", sa.Enum("high","interesting_with_doubts","low","insufficient_data", name="priorityrating"), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("llm_results")
    op.drop_table("sources")
    op.drop_table("analyses")
    op.drop_table("companies")