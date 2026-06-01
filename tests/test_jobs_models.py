from sqlalchemy import UniqueConstraint

from app.models import Base


def test_jobs_metadata_tables_are_registered() -> None:
    assert {
        "jobs",
        "job_attempts",
        "outbox_events",
        "webhook_events",
        "rate_limit_events",
    }.issubset(Base.metadata.tables)


def test_jobs_have_tenant_scoped_idempotency_constraint() -> None:
    table = Base.metadata.tables["jobs"]
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_jobs_tenant_type_idempotency"
        and [column.name for column in constraint.columns]
        == ["tenant_id", "job_type", "idempotency_key"]
        for constraint in constraints
    )


def test_webhook_events_are_tenant_provider_idempotent() -> None:
    table = Base.metadata.tables["webhook_events"]
    constraints = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_webhook_events_tenant_provider_idempotency"
        and [column.name for column in constraint.columns]
        == ["tenant_id", "provider", "idempotency_key"]
        for constraint in constraints
    )

