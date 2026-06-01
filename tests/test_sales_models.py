from sqlalchemy import Index

from app.models import Base


def test_sales_metadata_tables_are_registered() -> None:
    assert {"sales_contacts"}.issubset(Base.metadata.tables)


def test_sales_contacts_phone_is_unique_per_tenant_when_present() -> None:
    table = Base.metadata.tables["sales_contacts"]
    indexes = [index for index in table.indexes if isinstance(index, Index)]

    assert any(
        index.name == "uq_sales_contacts_tenant_phone_normalized"
        and index.unique
        and [column.name for column in index.columns] == ["tenant_id", "phone_normalized"]
        for index in indexes
    )
