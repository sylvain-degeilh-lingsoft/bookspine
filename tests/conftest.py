"""Builds a tiny synthetic EPUB fixture in-memory, exercising the same structural
edge cases seen in accessible_epub_3.epub: a nested <section>, a <li><p> pair (must
yield exactly one paragraph, not two), and a bare <div> used as a paragraph."""

import io
import zipfile

import pytest

CONTAINER_XML = b"""<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

PACKAGE_OPF = b"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/"
         version="3.0" unique-identifier="pub-id">
  <metadata>
    <dc:identifier id="pub-id">urn:isbn:9781234567890</dc:identifier>
    <dc:title>Test Book</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch01" href="ch01.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="nav" linear="no"/>
    <itemref idref="ch01"/>
  </spine>
</package>"""

NAV_XHTML = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>nav</title></head>
<body><nav epub:type="toc"><ol><li><a href="ch01.xhtml">Chapter 1</a></li></ol></nav></body>
</html>"""

CH01_XHTML = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>ch1</title></head>
<body>
<section class="chapter" epub:type="chapter" id="ch1">
  <h2>Chapter One</h2>
  <p>First paragraph of the chapter.</p>
  <div>A div used directly as a paragraph.</div>
  <section class="sect1" id="sect-a">
    <h2>Section A</h2>
    <p>A paragraph inside section A.</p>
    <ul>
      <li><p>List item text wrapped in a paragraph tag.</p></li>
    </ul>
  </section>
</section>
</body>
</html>"""


def build_epub_bytes() -> bytes:
    # Fixed date_time on every entry: zipfile.writestr(name, data) otherwise stamps
    # each entry with the current wall-clock time, so two calls to this function a
    # second apart would produce different bytes for byte-identical content.
    entries = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": CONTAINER_XML,
        "EPUB/package.opf": PACKAGE_OPF,
        "EPUB/nav.xhtml": NAV_XHTML,
        "EPUB/ch01.xhtml": CH01_XHTML,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            zf.writestr(info, data, compress_type=compress_type)
    return buf.getvalue()


@pytest.fixture
def sample_epub(tmp_path):
    path = tmp_path / "sample.epub"
    path.write_bytes(build_epub_bytes())
    return str(path)
