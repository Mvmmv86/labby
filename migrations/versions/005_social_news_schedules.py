"""social news schedules

Revision ID: 005_social_news_schedules
Revises: 004_social_news_foundation
Create Date: 2026-06-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005_social_news_schedules"
down_revision: str | None = "004_social_news_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE social_news_schedules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE CASCADE,
            name VARCHAR(120),
            timezone VARCHAR(80) NOT NULL DEFAULT 'America/Sao_Paulo',
            day_of_week INTEGER,
            window_start_hour INTEGER NOT NULL,
            window_end_hour INTEGER NOT NULL,
            scheduled_hour INTEGER NOT NULL,
            scheduled_minute INTEGER NOT NULL DEFAULT 0,
            confidence_score NUMERIC(5,2) NOT NULL DEFAULT 45,
            samples_count INTEGER NOT NULL DEFAULT 0,
            average_score NUMERIC(10,2),
            discovered_by VARCHAR(40) NOT NULL DEFAULT 'user',
            origin_run_id UUID REFERENCES social_news_runs(id) ON DELETE SET NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_social_news_schedules_status
                CHECK (status IN ('active', 'inactive', 'archived')),
            CONSTRAINT ck_social_news_schedules_day_of_week
                CHECK (day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)),
            CONSTRAINT ck_social_news_schedules_window_start_hour
                CHECK (window_start_hour >= 0 AND window_start_hour <= 23),
            CONSTRAINT ck_social_news_schedules_window_end_hour
                CHECK (window_end_hour >= 1 AND window_end_hour <= 24),
            CONSTRAINT ck_social_news_schedules_scheduled_hour
                CHECK (scheduled_hour >= 0 AND scheduled_hour <= 23),
            CONSTRAINT ck_social_news_schedules_scheduled_minute
                CHECK (scheduled_minute >= 0 AND scheduled_minute <= 59),
            CONSTRAINT ck_social_news_schedules_confidence_score
                CHECK (confidence_score >= 0 AND confidence_score <= 100),
            CONSTRAINT ck_social_news_schedules_samples_count CHECK (samples_count >= 0),
            CONSTRAINT ck_social_news_schedules_discovered_by
                CHECK (discovered_by IN ('ia', 'user', 'exploratorio_fixo'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_schedules_tenant_segment_status
        ON social_news_schedules(tenant_id, segment_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_schedules_next_run_at
        ON social_news_schedules(next_run_at)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_social_news_schedules_active_window
        ON social_news_schedules(
            tenant_id,
            segment_id,
            COALESCE(day_of_week, -1),
            window_start_hour
        )
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_social_news_schedules_active_window")
    op.execute("DROP INDEX IF EXISTS ix_social_news_schedules_next_run_at")
    op.execute("DROP INDEX IF EXISTS ix_social_news_schedules_tenant_segment_status")
    op.execute("DROP TABLE IF EXISTS social_news_schedules")
