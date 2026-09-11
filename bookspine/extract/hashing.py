import hashlib


def sha256_hex(data: bytes) -> str:
    """Prefixed sha256, matching the `sha256:<hex>` shape used in the publication record."""
    return "sha256:" + hashlib.sha256(data).hexdigest()
