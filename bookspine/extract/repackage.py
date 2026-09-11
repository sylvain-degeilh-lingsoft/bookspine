"""Writes the canonical EPUB copy: original bytes, with any modified content
documents (id-injection) substituted in. Byte-for-byte deterministic given the
same input and the same set of substitutions — fixed per-entry timestamps and the
original entry order — so `canonicalHash` is reproducible, not incidental."""

from __future__ import annotations

import io
import zipfile

FIXED_DATE_TIME = (2000, 1, 1, 0, 0, 0)


def build_canonical_epub(source_zip_path: str, modified_docs: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(source_zip_path) as zin:
        names = zin.namelist()
        with zipfile.ZipFile(buffer, "w") as zout:
            for name in names:
                data = modified_docs.get(name, zin.read(name))
                info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
                info.external_attr = 0o644 << 16
                compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                zout.writestr(info, data, compress_type=compress_type)
    return buffer.getvalue()
