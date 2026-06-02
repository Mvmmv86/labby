from sqlalchemy import Index

from app.models import Base


def test_sales_metadata_tables_are_registered() -> None:
    assert {
        "sales_campaign_recipients",
        "sales_campaigns",
        "sales_channels",
        "sales_contact_channels",
        "sales_contacts",
        "sales_conversations",
        "sales_messages",
    }.issubset(Base.metadata.tables)


def test_sales_contacts_phone_is_unique_per_tenant_when_present() -> None:
    table = Base.metadata.tables["sales_contacts"]
    indexes = [index for index in table.indexes if isinstance(index, Index)]

    assert any(
        index.name == "uq_sales_contacts_tenant_phone_normalized"
        and index.unique
        and [column.name for column in index.columns] == ["tenant_id", "phone_normalized"]
        for index in indexes
    )


def test_sales_campaigns_are_tenant_idempotent() -> None:
    table = Base.metadata.tables["sales_campaigns"]
    indexes = [index for index in table.indexes if isinstance(index, Index)]

    assert any(
        index.name == "uq_sales_campaigns_tenant_idempotency"
        and index.unique
        and [column.name for column in index.columns] == ["tenant_id", "idempotency_key"]
        for index in indexes
    )


def test_sales_campaign_recipients_are_unique_per_campaign_contact() -> None:
    table = Base.metadata.tables["sales_campaign_recipients"]
    indexes = [index for index in table.indexes if isinstance(index, Index)]

    assert any(
        index.name == "uq_sales_campaign_recipients_campaign_contact"
        and index.unique
        and [column.name for column in index.columns]
        == ["tenant_id", "campaign_id", "contact_id"]
        for index in indexes
    )


def test_sales_messages_external_id_is_unique_per_tenant_provider() -> None:
    table = Base.metadata.tables["sales_messages"]
    indexes = [index for index in table.indexes if isinstance(index, Index)]

    assert any(
        index.name == "uq_sales_messages_tenant_provider_external"
        and index.unique
        and [column.name for column in index.columns] == ["tenant_id", "provider", "external_id"]
        for index in indexes
    )
