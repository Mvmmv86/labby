"""social news foundation

Revision ID: 004_social_news_foundation
Revises: 003_jobs_outbox_foundation
Create Date: 2026-06-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004_social_news_foundation"
down_revision: str | None = "003_jobs_outbox_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE social_news_segments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            slug VARCHAR(120) NOT NULL,
            name VARCHAR(180) NOT NULL,
            description TEXT,
            base_knowledge TEXT,
            disclaimer TEXT,
            min_engagement_score INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_segments_tenant_slug UNIQUE (tenant_id, slug),
            CONSTRAINT ck_social_news_segments_status
                CHECK (status IN ('active', 'inactive', 'archived')),
            CONSTRAINT ck_social_news_segments_min_engagement_non_negative
                CHECK (min_engagement_score >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_segments_tenant_status_created_at
        ON social_news_segments(tenant_id, status, created_at)
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE CASCADE,
            provider VARCHAR(40) NOT NULL DEFAULT 'x',
            source_type VARCHAR(40) NOT NULL,
            value VARCHAR(500) NOT NULL,
            min_likes INTEGER NOT NULL DEFAULT 0,
            min_reposts INTEGER NOT NULL DEFAULT 0,
            min_replies INTEGER NOT NULL DEFAULT 0,
            min_impressions INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_sources_tenant_segment_source
                UNIQUE (tenant_id, segment_id, provider, source_type, value),
            CONSTRAINT ck_social_news_sources_provider CHECK (provider IN ('x')),
            CONSTRAINT ck_social_news_sources_type
                CHECK (source_type IN ('x_handle', 'x_keyword', 'x_query')),
            CONSTRAINT ck_social_news_sources_status
                CHECK (status IN ('active', 'inactive', 'archived')),
            CONSTRAINT ck_social_news_sources_min_likes_non_negative CHECK (min_likes >= 0),
            CONSTRAINT ck_social_news_sources_min_reposts_non_negative CHECK (min_reposts >= 0),
            CONSTRAINT ck_social_news_sources_min_replies_non_negative CHECK (min_replies >= 0),
            CONSTRAINT ck_social_news_sources_min_impressions_non_negative
                CHECK (min_impressions >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_sources_tenant_segment_status
        ON social_news_sources(tenant_id, segment_id, status)
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_curators (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE CASCADE,
            name VARCHAR(180) NOT NULL,
            model VARCHAR(80) NOT NULL DEFAULT 'gpt-4o-mini',
            temperature NUMERIC(3,2) NOT NULL DEFAULT 0.30,
            max_tokens INTEGER NOT NULL DEFAULT 600,
            system_prompt TEXT,
            base_knowledge TEXT,
            vocabulary JSONB NOT NULL DEFAULT '[]'::jsonb,
            event_types JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            updated_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_curators_tenant_segment UNIQUE (tenant_id, segment_id),
            CONSTRAINT ck_social_news_curators_status
                CHECK (status IN ('active', 'inactive', 'archived')),
            CONSTRAINT ck_social_news_curators_temperature_min CHECK (temperature >= 0),
            CONSTRAINT ck_social_news_curators_temperature_max CHECK (temperature <= 2),
            CONSTRAINT ck_social_news_curators_max_tokens_positive CHECK (max_tokens > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE RESTRICT,
            job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
            run_type VARCHAR(30) NOT NULL DEFAULT 'manual',
            status VARCHAR(30) NOT NULL DEFAULT 'queued',
            idempotency_key VARCHAR(180) NOT NULL,
            window_start_at TIMESTAMPTZ,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            candidates_count INTEGER NOT NULL DEFAULT 0,
            ranked_count INTEGER NOT NULL DEFAULT 0,
            approved_stage1_count INTEGER NOT NULL DEFAULT 0,
            approved_stage2_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            x_api_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
            ai_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
            email_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
            estimated_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
            error_code VARCHAR(120),
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_runs_tenant_type_idempotency
                UNIQUE (tenant_id, run_type, idempotency_key),
            CONSTRAINT ck_social_news_runs_type
                CHECK (run_type IN ('manual', 'scheduled', 'calibration')),
            CONSTRAINT ck_social_news_runs_status
                CHECK (status IN (
                    'queued', 'capturing', 'curation_stage1', 'rewriting',
                    'curation_stage2', 'sending', 'succeeded', 'failed', 'cancelled'
                )),
            CONSTRAINT ck_social_news_runs_candidates_count CHECK (candidates_count >= 0),
            CONSTRAINT ck_social_news_runs_ranked_count CHECK (ranked_count >= 0),
            CONSTRAINT ck_social_news_runs_approved_s1 CHECK (approved_stage1_count >= 0),
            CONSTRAINT ck_social_news_runs_approved_s2 CHECK (approved_stage2_count >= 0),
            CONSTRAINT ck_social_news_runs_sent_count CHECK (sent_count >= 0),
            CONSTRAINT ck_social_news_runs_failed_count CHECK (failed_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_runs_tenant_status_created_at
        ON social_news_runs(tenant_id, status, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_runs_tenant_segment_created_at
        ON social_news_runs(tenant_id, segment_id, created_at)
        """
    )
    op.execute("CREATE INDEX ix_social_news_runs_job_id ON social_news_runs(job_id)")

    op.execute(
        """
        CREATE TABLE social_news_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            run_id UUID NOT NULL REFERENCES social_news_runs(id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE RESTRICT,
            source_id UUID REFERENCES social_news_sources(id) ON DELETE SET NULL,
            provider VARCHAR(40) NOT NULL DEFAULT 'x',
            external_id VARCHAR(180) NOT NULL,
            external_url TEXT,
            published_at TIMESTAMPTZ,
            author_handle VARCHAR(180),
            author_name VARCHAR(240),
            author_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            original_content TEXT NOT NULL,
            rewritten_content TEXT,
            rewritten_model VARCHAR(80),
            rewritten_at TIMESTAMPTZ,
            media_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            ranking_score INTEGER,
            ranking_reason TEXT,
            ranking_source VARCHAR(80),
            type_match VARCHAR(120),
            status VARCHAR(30) NOT NULL DEFAULT 'captured',
            approved_stage1_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            approved_stage1_at TIMESTAMPTZ,
            approved_stage2_by_membership_id UUID REFERENCES memberships(id) ON DELETE SET NULL,
            approved_stage2_at TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_items_tenant_provider_external
                UNIQUE (tenant_id, provider, external_id),
            CONSTRAINT ck_social_news_items_provider CHECK (provider IN ('x')),
            CONSTRAINT ck_social_news_items_status
                CHECK (status IN (
                    'captured', 'ranked', 'discarded_rank', 'approved_stage1',
                    'rejected_stage1', 'rewritten', 'approved_stage2',
                    'rejected_stage2', 'sent'
                ))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_items_tenant_run_status
        ON social_news_items(tenant_id, run_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_items_tenant_segment_status
        ON social_news_items(tenant_id, segment_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_items_tenant_created_at
        ON social_news_items(tenant_id, created_at)
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_subscribers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            segment_id UUID NOT NULL REFERENCES social_news_segments(id) ON DELETE CASCADE,
            email_normalized VARCHAR(320) NOT NULL,
            name VARCHAR(180),
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            origin VARCHAR(80) NOT NULL DEFAULT 'manual',
            consent_status VARCHAR(30) NOT NULL DEFAULT 'granted',
            consent_source VARCHAR(80),
            consent_given_at TIMESTAMPTZ,
            unsubscribed_at TIMESTAMPTZ,
            unsubscribe_token_hash VARCHAR(128),
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_subscribers_tenant_segment_email
                UNIQUE (tenant_id, segment_id, email_normalized),
            CONSTRAINT ck_social_news_subscribers_status
                CHECK (status IN (
                    'active', 'unsubscribed', 'bounced', 'complained', 'removed'
                )),
            CONSTRAINT ck_social_news_subscribers_consent_status
                CHECK (consent_status IN ('granted', 'revoked'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_subscribers_tenant_segment_status
        ON social_news_subscribers(tenant_id, segment_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_subscribers_unsubscribe_hash
        ON social_news_subscribers(unsubscribe_token_hash)
        WHERE unsubscribe_token_hash IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_subscriber_consent_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            subscriber_id UUID NOT NULL REFERENCES social_news_subscribers(id) ON DELETE CASCADE,
            event_type VARCHAR(80) NOT NULL,
            consent_source VARCHAR(80),
            ip VARCHAR(80),
            user_agent VARCHAR(500),
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_consent_events_subscriber_created_at
        ON social_news_subscriber_consent_events(subscriber_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_consent_events_tenant_type_created_at
        ON social_news_subscriber_consent_events(tenant_id, event_type, created_at)
        """
    )

    op.execute(
        """
        CREATE TABLE social_news_dispatches (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            run_id UUID NOT NULL REFERENCES social_news_runs(id) ON DELETE CASCADE,
            subscriber_id UUID NOT NULL REFERENCES social_news_subscribers(id) ON DELETE CASCADE,
            email_normalized VARCHAR(320) NOT NULL,
            subject VARCHAR(240) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            idempotency_key VARCHAR(180) NOT NULL,
            provider VARCHAR(80) NOT NULL DEFAULT 'resend',
            provider_message_id VARCHAR(180),
            error_message TEXT,
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_social_news_dispatches_tenant_idempotency
                UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT uq_social_news_dispatches_run_subscriber UNIQUE (run_id, subscriber_id),
            CONSTRAINT ck_social_news_dispatches_status
                CHECK (status IN ('pending', 'sent', 'failed', 'skipped'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_dispatches_tenant_run_status
        ON social_news_dispatches(tenant_id, run_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_social_news_dispatches_tenant_subscriber_created_at
        ON social_news_dispatches(tenant_id, subscriber_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_social_news_dispatches_tenant_subscriber_created_at")
    op.execute("DROP INDEX IF EXISTS ix_social_news_dispatches_tenant_run_status")
    op.execute("DROP TABLE IF EXISTS social_news_dispatches")
    op.execute("DROP INDEX IF EXISTS ix_social_news_consent_events_tenant_type_created_at")
    op.execute("DROP INDEX IF EXISTS ix_social_news_consent_events_subscriber_created_at")
    op.execute("DROP TABLE IF EXISTS social_news_subscriber_consent_events")
    op.execute("DROP INDEX IF EXISTS ix_social_news_subscribers_unsubscribe_hash")
    op.execute("DROP INDEX IF EXISTS ix_social_news_subscribers_tenant_segment_status")
    op.execute("DROP TABLE IF EXISTS social_news_subscribers")
    op.execute("DROP INDEX IF EXISTS ix_social_news_items_tenant_created_at")
    op.execute("DROP INDEX IF EXISTS ix_social_news_items_tenant_segment_status")
    op.execute("DROP INDEX IF EXISTS ix_social_news_items_tenant_run_status")
    op.execute("DROP TABLE IF EXISTS social_news_items")
    op.execute("DROP INDEX IF EXISTS ix_social_news_runs_job_id")
    op.execute("DROP INDEX IF EXISTS ix_social_news_runs_tenant_segment_created_at")
    op.execute("DROP INDEX IF EXISTS ix_social_news_runs_tenant_status_created_at")
    op.execute("DROP TABLE IF EXISTS social_news_runs")
    op.execute("DROP TABLE IF EXISTS social_news_curators")
    op.execute("DROP INDEX IF EXISTS ix_social_news_sources_tenant_segment_status")
    op.execute("DROP TABLE IF EXISTS social_news_sources")
    op.execute("DROP INDEX IF EXISTS ix_social_news_segments_tenant_status_created_at")
    op.execute("DROP TABLE IF EXISTS social_news_segments")
