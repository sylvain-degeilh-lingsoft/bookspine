from __future__ import annotations

import json
from pathlib import Path

import click

from bookspine import service
from bookspine.extract.epub_reader import EpubFormatError
from bookspine.storage import db as db_module


@click.group()
def main() -> None:
    """BookSpine: paragraph-level EPUB structure/Locator extraction."""


@main.command()
@click.argument("epub_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--strategy",
    type=click.Choice(["id", "selector", "auto"]),
    default="auto",
    show_default=True,
)
@click.option("-o", "--out", "out_dir", type=click.Path(file_okay=False), default="./out", show_default=True)
@click.option(
    "--db",
    "db_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="SQLite db to register the result in (default: <out>/bookspine.db).",
)
def extract(epub_path: str, strategy: str, out_dir: str, db_path: str | None) -> None:
    """Extract the paragraph tree + Locators from EPUB_PATH into OUT."""
    db_path = db_path or str(Path(out_dir) / "bookspine.db")
    conn = db_module.connect(db_path)
    try:
        record, unchanged = service.process_epub(conn, out_dir, epub_path, strategy)
    except EpubFormatError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        conn.close()

    click.echo(json.dumps(record, indent=2))
    if unchanged:
        click.echo("sourceHash unchanged — no-op (already processed)", err=True)
    else:
        click.echo(f"\nWrote {out_dir}/publications/{record['bookId']}/", err=True)


@main.command()
@click.argument("paragraph_id")
@click.option("--db", "db_path", type=click.Path(exists=True, dir_okay=False), required=True)
def resolve(paragraph_id: str, db_path: str) -> None:
    """Look up a paragraphId -> Locator directly against a BookSpine SQLite db."""
    conn = db_module.connect(db_path)
    try:
        para = db_module.get_paragraph(conn, paragraph_id)
    finally:
        conn.close()

    if para is None:
        raise click.ClickException(f"paragraph not found: {paragraph_id}")
    click.echo(json.dumps(para["locator"], indent=2))


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, type=int, show_default=True)
def serve(host: str, port: int) -> None:
    """Run the BookSpine API (reads BOOKSPINE_DATA env var, default ./data)."""
    import uvicorn

    uvicorn.run("bookspine.api.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
