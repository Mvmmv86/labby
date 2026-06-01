from sqlalchemy import UniqueConstraint

from app.models import Base


def test_social_news_metadata_tables_are_registered() -> None:
    assert {
        "social_news_segments",
        "social_news_sources",
        "social_news_curators",
        "social_news_runs",
        "social_news_items",
        "social_news_subscribers",
        "social_news_subscriber_consent_events",
        "social_news_dispatches",
        "social_news_schedules",
    }.issubset(Base.metadata.tables)


def test_social_news_runs_are_tenant_idempotent() -> None:
    table = Base.metadata.tables["social_news_runs"]
    constraints = [
        constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_social_news_runs_tenant_type_idempotency"
        and [column.name for column in constraint.columns]
        == ["tenant_id", "run_type", "idempotency_key"]
        for constraint in constraints
    )


def test_social_news_items_are_tenant_provider_external_unique() -> None:
    table = Base.metadata.tables["social_news_items"]
    constraints = [
        constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_social_news_items_tenant_provider_external"
        and [column.name for column in constraint.columns]
        == ["tenant_id", "provider", "external_id"]
        for constraint in constraints
    )
