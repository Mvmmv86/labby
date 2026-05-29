import re
import unicodedata


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_value.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-") or "tenant"
