import pytest

from app.domains.identity.modules import ModuleAccess
from app.domains.identity.normalization import normalize_email, slugify


def test_normalize_email_uses_nfkc_and_lowercase() -> None:
    assert normalize_email("  MARCUS@EXAMPLE.COM  ") == "marcus@example.com"


def test_slugify_removes_accents_and_symbols() -> None:
    assert slugify("Labby Comunicação!") == "labby-comunicacao"


def test_module_access_requires_default_module_to_be_enabled() -> None:
    access = ModuleAccess(modules=("sales",), default_module="social_media")
    with pytest.raises(ValueError, match="Modulo padrao"):
        access.validate()


def test_module_access_requires_at_least_one_module() -> None:
    access = ModuleAccess(modules=(), default_module="sales")
    with pytest.raises(ValueError, match="Pelo menos um modulo"):
        access.validate()
