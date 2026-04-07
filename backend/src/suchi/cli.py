"""Suchi CLI — Unix-first reference manager.

Every command supports --json for pipe-friendly output.
All output goes to stdout; errors go to stderr.

Examples:
    suchi add 10.1038/nature12373
    suchi add --file paper.pdf
    suchi search "machine learning" --tag cs.CR --json | jq '.[].title'
    suchi list --json | jq '.[] | select(.date > "2023")'
    suchi collect thesis/chapter-1 <entry-id>
    suchi export --format bibtex | pbcopy
    suchi collection create "My Collection" --parent thesis
    suchi collection tree
    suchi tags
    suchi stats
"""

import asyncio
import json as json_module
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from . import library
from . import collections as col_service
from .config import get_config

app = typer.Typer(
    name="suchi",
    help="सूची — CLI-first reference manager with AI-powered research tools.",
    no_args_is_help=True,
)
console = Console(stderr=True)  # Rich output to stderr so stdout is pipe-clean
out = Console()  # stdout for data output


def _run_async(coro):
    return asyncio.run(coro)


def _print_json(data):
    """Print JSON to stdout."""
    print(json_module.dumps(data, indent=2, default=str))


def _entry_summary(entry: dict) -> dict:
    """Slim entry dict for JSON output."""
    return {
        "id": entry.get("id", ""),
        "title": entry.get("title", ""),
        "author": [f"{a.get('given','')} {a.get('family','')}".strip() for a in entry.get("author", [])],
        "date": entry.get("date"),
        "doi": entry.get("doi"),
        "journal": entry.get("journal"),
        "tags": entry.get("tags", []),
        "collections": entry.get("collections", []),
        "files": entry.get("files", []),
    }


# ─── ENTRIES ────────────────────────────────────────────────────────

@app.command()
def add(
    identifier: Optional[str] = typer.Argument(None, help="DOI, ISBN, arXiv ID, or URL"),
    manual: bool = typer.Option(False, "--manual", "-m", help="Add entry interactively"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="PDF file to add (extracts metadata)"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags to add"),
    collection: list[str] = typer.Option([], "--collection", "-c", help="Collections to add to"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Add a reference by DOI, ISBN, arXiv ID, URL, PDF file, or manually."""
    if file and file.exists():
        # Upload PDF — extract metadata
        with console.status("Extracting metadata from PDF..."):
            from .translators.pdf_extract import extract_metadata_from_pdf, parse_raw_authors
            from .translators.resolver import resolve_identifier
            from .translators.crossref import search_by_title as crossref_search
            from .translators.semantic_scholar import search_by_title as s2_search

            pdf_meta = extract_metadata_from_pdf(file)
            resolved = None

            if pdf_meta.get("doi"):
                resolved = _run_async(resolve_identifier(pdf_meta["doi"]))
            if not resolved and pdf_meta.get("arxiv_id"):
                resolved = _run_async(resolve_identifier(pdf_meta["arxiv_id"]))
            if not resolved and pdf_meta.get("title"):
                resolved = _run_async(crossref_search(pdf_meta["title"]))
            if not resolved and pdf_meta.get("title"):
                try:
                    resolved = _run_async(s2_search(pdf_meta["title"]))
                except Exception:
                    pass

        if resolved:
            resolved.pop("pdf_url", None)
            api_tags = resolved.pop("tags", []) or []
            pdf_kw = pdf_meta.get("keywords", [])
            metadata = {**resolved, "tags": list(dict.fromkeys(api_tags + pdf_kw + tags)), "collections": collection}
        else:
            metadata = {
                "type": "article",
                "title": pdf_meta.get("title") or file.stem,
                "author": parse_raw_authors(pdf_meta["raw_author"]) if pdf_meta.get("raw_author") else [],
                "tags": pdf_meta.get("keywords", []) + tags,
                "collections": collection,
            }
            if pdf_meta.get("doi"): metadata["doi"] = pdf_meta["doi"]
            if pdf_meta.get("date"): metadata["date"] = pdf_meta["date"]
            if pdf_meta.get("abstract"): metadata["abstract"] = pdf_meta["abstract"]

        entry = library.add_entry_manual(metadata)
        # Copy PDF as document.pdf
        entry_dir = library.get_entry_dir(entry["id"])
        dest = entry_dir / "document.pdf"
        shutil.copy2(file, dest)
        entry = library.attach_file(entry["id"], dest)

        if json:
            _print_json(_entry_summary(entry))
        else:
            console.print(f"[green]Added:[/green] {entry['title']}")
            console.print(f"  [dim]{entry['id']}[/dim]")
        return

    if manual:
        title = typer.prompt("Title")
        entry_type = typer.prompt("Type (article/book/inproceedings/thesis)", default="article")
        author_str = typer.prompt("Authors (semicolon-separated: 'First Last; First Last')", default="")
        doi = typer.prompt("DOI", default="")
        date = typer.prompt("Date (YYYY or YYYY-MM-DD)", default="")
        journal = typer.prompt("Journal/Venue", default="")

        authors = []
        if author_str:
            for a in author_str.split(";"):
                a = a.strip()
                parts = a.rsplit(" ", 1)
                if len(parts) == 2:
                    authors.append({"given": parts[0], "family": parts[1]})
                else:
                    authors.append({"family": a, "given": ""})

        metadata = {"type": entry_type, "title": title, "author": authors, "tags": tags, "collections": collection}
        if doi: metadata["doi"] = doi
        if date: metadata["date"] = date
        if journal: metadata["journal"] = journal

        entry = library.add_entry_manual(metadata)
        if json:
            _print_json(_entry_summary(entry))
        else:
            console.print(f"[green]Added:[/green] {entry['title']} [{entry['id']}]")
        return

    if not identifier:
        console.print("[red]Error:[/red] Provide an identifier, --file, or --manual")
        raise typer.Exit(1)

    with console.status("Resolving..."):
        entry = _run_async(library.add_entry_by_identifier(identifier, tags=tags or None, collections=collection or None))

    if not entry:
        console.print(f"[red]Error:[/red] Could not resolve: {identifier}")
        raise typer.Exit(1)

    if json:
        _print_json(_entry_summary(entry))
    else:
        console.print(f"[green]Added:[/green] {entry['title']} [{entry['id']}]")


@app.command(name="list")
def list_entries(
    tag: Optional[str] = typer.Option(None, "--tag", "-t"),
    collection: Optional[str] = typer.Option(None, "--collection", "-c"),
    limit: int = typer.Option(100, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all references. Filterable by tag or collection."""
    entries = library.list_entries(tag=tag, collection=collection, limit=limit)

    if json:
        _print_json([_entry_summary(e) for e in entries])
        return

    if not entries:
        console.print("[dim]No entries found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", max_width=40)
    table.add_column("Title", max_width=50)
    table.add_column("Author", max_width=25)
    table.add_column("Year", width=6)
    table.add_column("Tags", max_width=25)

    for entry in entries:
        authors = entry.get("author", [])
        author_str = authors[0].get("family", "") if authors else ""
        if len(authors) > 1: author_str += " et al."
        date = entry.get("date", "")
        year = date.split("-")[0] if date else ""
        table.add_row(entry["id"], entry.get("title", ""), author_str, year, ", ".join(entry.get("tags", [])))

    out.print(table)
    console.print(f"[dim]{len(entries)} entries[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (supports typos)"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    author: Optional[str] = typer.Option(None, "--author", "-a", help="Filter by author"),
    year: Optional[str] = typer.Option(None, "--year", "-y", help="Filter by year"),
    journal: Optional[str] = typer.Option(None, "--journal", "-j", help="Filter by journal"),
    limit: int = typer.Option(20, "--limit", "-n"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Search references (full-text + fuzzy). Supports typos."""
    from .search import search as engine_search, SearchFilters
    filters = SearchFilters(year=year, author=author, tag=tag, journal=journal)
    results = engine_search(query, filters=filters, limit=limit)

    if json:
        _print_json([_entry_summary(r) for r in results])
        return

    if not results:
        console.print("[dim]No results.[/dim]")
        return

    for entry in results:
        authors = entry.get("author", [])
        author_str = ", ".join(a.get("family", "") for a in authors[:3])
        if len(authors) > 3: author_str += " et al."
        year_str = (entry.get("date", "") or "").split("-")[0]

        out.print(f"[bold]{entry.get('title', '')}[/bold]")
        out.print(f"  {author_str} ({year_str})")
        if entry.get("doi"): out.print(f"  DOI: {entry['doi']}")
        out.print(f"  [dim]{entry['id']}[/dim]")
        out.print()


@app.command()
def info(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show detailed info about an entry."""
    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
        raise typer.Exit(1)

    if json:
        _print_json(entry)
        return

    out.print(f"[bold]{entry.get('title', 'Untitled')}[/bold]\n")
    authors = entry.get("author", [])
    if authors:
        author_strs = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in authors]
        out.print(f"  Authors:     {', '.join(author_strs)}")
    for field, label in [("type","Type"),("date","Date"),("journal","Journal"),("volume","Volume"),("issue","Issue"),("pages","Pages"),("publisher","Publisher"),("doi","DOI"),("isbn","ISBN"),("url","URL")]:
        val = entry.get(field)
        if val: out.print(f"  {label+':':12s} {val}")
    if entry.get("tags"): out.print(f"  {'Tags:':12s} {', '.join(entry['tags'])}")
    if entry.get("collections"): out.print(f"  {'Collections:':12s} {', '.join(entry['collections'])}")
    if entry.get("files"): out.print(f"  {'Files:':12s} {', '.join(entry['files'])}")
    if entry.get("abstract"): out.print(f"\n  [dim]Abstract:[/dim]\n  {entry['abstract'][:500]}")


@app.command()
def edit(entry_id: str = typer.Argument(..., help="Entry ID")):
    """Open an entry's info.yaml in $EDITOR."""
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)
    editor = get_config().editor or os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(entry_dir / "info.yaml")])


@app.command()
def remove(
    entry_ids: list[str] = typer.Argument(..., help="Entry ID(s) to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove one or more entries."""
    for entry_id in entry_ids:
        entry = library.get_entry(entry_id)
        if not entry:
            console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
            continue
        if not force:
            if not typer.confirm(f"Remove '{entry.get('title', entry_id)}'?"): continue
        library.delete_entry(entry_id)
        console.print(f"[green]Removed:[/green] {entry_id}")


@app.command(name="open")
def open_entry(query: str = typer.Argument(..., help="Entry ID or search term")):
    """Open a reference's PDF in the default viewer."""
    entry = library.get_entry(query)
    if not entry:
        results = library.search_entries(query, limit=1)
        entry = results[0] if results else None
    if not entry:
        console.print(f"[red]Error:[/red] Not found: {query}"); raise typer.Exit(1)
    entry_dir = library.get_entry_dir(entry["id"])
    pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
    if not pdfs:
        console.print("[yellow]No PDF attached.[/yellow]"); raise typer.Exit(1)
    path = str(entry_dir / pdfs[0])
    if sys.platform == "darwin": subprocess.run(["open", path])
    elif sys.platform == "linux": subprocess.run(["xdg-open", path])
    else: os.startfile(path)


@app.command()
def note(entry_id: str = typer.Argument(..., help="Entry ID")):
    """Open or create notes for an entry in $EDITOR."""
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)
    notes = entry_dir / "notes.md"
    if not notes.exists():
        entry = library.get_entry(entry_id)
        notes.write_text(f"# Notes: {entry.get('title', entry_id) if entry else entry_id}\n\n")
    editor = get_config().editor or os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(notes)])


# ─── TAGS ───────────────────────────────────────────────────────────

@app.command()
def tag(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    add_tags: list[str] = typer.Option([], "--add", "-a", help="Tags to add"),
    remove: list[str] = typer.Option([], "--remove", "-r", help="Tags to remove"),
    json: bool = typer.Option(False, "--json"),
):
    """Add or remove tags on an entry."""
    if add_tags:
        result = library.add_tags(entry_id, add_tags)
        if not result: console.print(f"[red]Error:[/red] Not found: {entry_id}"); raise typer.Exit(1)
        console.print(f"[green]+[/green] {', '.join(add_tags)}")
    if remove:
        result = library.remove_tags(entry_id, remove)
        if not result: console.print(f"[red]Error:[/red] Not found: {entry_id}"); raise typer.Exit(1)
        console.print(f"[red]-[/red] {', '.join(remove)}")
    entry = library.get_entry(entry_id)
    if entry:
        if json:
            _print_json(entry.get("tags", []))
        else:
            console.print(f"[dim]Tags:[/dim] {', '.join(entry.get('tags', []))}")


@app.command()
def tags(json: bool = typer.Option(False, "--json")):
    """List all tags in the library."""
    all_tags = library.get_all_tags()
    if json:
        _print_json(all_tags)
    else:
        for t in all_tags:
            out.print(t)


# ─── COLLECTIONS ────────────────────────────────────────────────────

collection_app = typer.Typer(name="collection", help="Manage collections (folders).", no_args_is_help=True)
app.add_typer(collection_app)


@collection_app.command("create")
def collection_create(
    name: str = typer.Argument(..., help="Collection name"),
    parent: Optional[str] = typer.Option(None, "--parent", "-p", help="Parent collection ID"),
    json: bool = typer.Option(False, "--json"),
):
    """Create a new collection."""
    try:
        col = col_service.create_collection(name, parent_id=parent)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}"); raise typer.Exit(1)
    if json:
        _print_json(col)
    else:
        console.print(f"[green]Created:[/green] {col['name']} [{col['id']}]")


@collection_app.command("list")
def collection_list(json: bool = typer.Option(False, "--json")):
    """List all collections (flat)."""
    cols = col_service.get_collections_flat()
    if json:
        _print_json(cols)
    else:
        for c in cols:
            indent = "  " * c["id"].count("/")
            out.print(f"{indent}{c['name']}  [dim]{c['id']}[/dim]")


@collection_app.command("tree")
def collection_tree(json: bool = typer.Option(False, "--json")):
    """Show collection tree."""
    tree_data = col_service.get_collection_tree()
    if json:
        _print_json(tree_data)
        return

    if not tree_data:
        console.print("[dim]No collections.[/dim]")
        return

    rich_tree = Tree("[bold]Collections[/bold]")
    def add_nodes(parent, nodes):
        for n in nodes:
            branch = parent.add(f"{n['name']}  [dim]{n['id']}[/dim]")
            if n.get("children"):
                add_nodes(branch, n["children"])
    add_nodes(rich_tree, tree_data)
    out.print(rich_tree)


@collection_app.command("rename")
def collection_rename(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    name: str = typer.Argument(..., help="New name"),
):
    """Rename a collection."""
    result = col_service.rename_collection(collection_id, name)
    if not result:
        console.print(f"[red]Error:[/red] Not found: {collection_id}"); raise typer.Exit(1)
    console.print(f"[green]Renamed:[/green] {name}")


@collection_app.command("move")
def collection_move(
    collection_id: str = typer.Argument(..., help="Collection ID to move"),
    parent: Optional[str] = typer.Option(None, "--parent", "-p", help="New parent (omit for root)"),
):
    """Move a collection under a new parent."""
    try:
        result = col_service.move_collection(collection_id, parent)
        if not result:
            console.print(f"[red]Error:[/red] Not found: {collection_id}"); raise typer.Exit(1)
        console.print(f"[green]Moved:[/green] {collection_id} → {parent or 'root'}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}"); raise typer.Exit(1)


@collection_app.command("delete")
def collection_delete(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Also delete sub-collections"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a collection."""
    col = col_service.get_collection(collection_id)
    if not col:
        console.print(f"[red]Error:[/red] Not found: {collection_id}"); raise typer.Exit(1)
    if not force:
        if not typer.confirm(f"Delete collection '{col['name']}'?"): raise typer.Abort()
    if not col_service.delete_collection(collection_id, delete_children=recursive):
        console.print("[red]Error:[/red] Failed to delete"); raise typer.Exit(1)
    console.print(f"[green]Deleted:[/green] {collection_id}")


@collection_app.command("merge")
def collection_merge(
    source: str = typer.Argument(..., help="Source collection ID (will be deleted)"),
    target: str = typer.Argument(..., help="Target collection ID (entries moved here)"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """Merge one collection into another. Moves all entries, then deletes source."""
    src = col_service.get_collection(source)
    tgt = col_service.get_collection(target)
    if not src:
        console.print(f"[red]Error:[/red] Source not found: {source}"); raise typer.Exit(1)
    if not tgt:
        console.print(f"[red]Error:[/red] Target not found: {target}"); raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Merge '{src['name']}' into '{tgt['name']}'?"): raise typer.Abort()

    # Move entries from source to target
    entries = library.list_entries(limit=100_000)
    moved = 0
    for entry in entries:
        if source in entry.get("collections", []):
            cols = entry["collections"]
            cols.remove(source)
            if target not in cols:
                cols.append(target)
            library.update_entry(entry["id"], {"collections": cols})
            moved += 1

    col_service.delete_collection(source, delete_children=False)
    console.print(f"[green]Merged:[/green] {moved} entries moved, '{src['name']}' deleted")


# ─── COLLECT / UNCOLLECT ────────────────────────────────────────────

@app.command()
def collect(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    entry_ids: list[str] = typer.Argument(..., help="Entry ID(s) to add"),
):
    """Add entries to a collection.  Usage: suchi collect <collection> <entry1> <entry2> ..."""
    col = col_service.get_collection(collection_id)
    if not col:
        console.print(f"[red]Error:[/red] Collection not found: {collection_id}"); raise typer.Exit(1)

    for eid in entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            console.print(f"[yellow]Skip:[/yellow] Entry not found: {eid}")
            continue
        cols = entry.get("collections", [])
        if collection_id not in cols:
            cols.append(collection_id)
            library.update_entry(eid, {"collections": cols})
            console.print(f"[green]+[/green] {entry.get('title', eid)[:60]} → {col['name']}")
        else:
            console.print(f"[dim]Already in:[/dim] {eid}")


@app.command()
def uncollect(
    collection_id: str = typer.Argument(..., help="Collection ID"),
    entry_ids: list[str] = typer.Argument(..., help="Entry ID(s) to remove"),
):
    """Remove entries from a collection.  Usage: suchi uncollect <collection> <entry1> ..."""
    for eid in entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            console.print(f"[yellow]Skip:[/yellow] Entry not found: {eid}"); continue
        cols = entry.get("collections", [])
        if collection_id in cols:
            cols.remove(collection_id)
            library.update_entry(eid, {"collections": cols})
            console.print(f"[red]-[/red] {entry.get('title', eid)[:60]}")


# ─── FILES ──────────────────────────────────────────────────────────

@app.command(name="find-pdf")
def find_pdf_cmd(
    entry_ids: list[str] = typer.Argument(None, help="Entry ID(s) (omit for all entries without PDFs)"),
    download: bool = typer.Option(True, "--download/--no-download", help="Download the PDF if found"),
):
    """Find and download available PDFs (Unpaywall, arXiv, DOI).

    suchi find-pdf <entry-id>                # Find PDF for one entry
    suchi find-pdf                            # Find PDFs for all entries missing them
    suchi find-pdf <id> --no-download         # Just show sources, don't download
    """
    from .translators.pdf_finder import find_pdf as _find_pdf, download_pdf as _download_pdf

    # If no entry IDs, find all entries without PDFs
    if not entry_ids:
        all_entries = library.list_entries(limit=100_000)
        entry_ids = [
            e["id"] for e in all_entries
            if not any(f.endswith(".pdf") for f in e.get("files", []))
        ]
        if not entry_ids:
            console.print("[green]All entries have PDFs.[/green]")
            return
        console.print(f"[dim]Found {len(entry_ids)} entries without PDFs[/dim]")

    for eid in entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            console.print(f"[red]Not found:[/red] {eid}")
            continue

        title = entry.get("title", eid)[:50]
        with console.status(f"[purple]Searching: {title}...[/purple]"):
            sources = _run_async(_find_pdf(
                doi=entry.get("doi"),
                arxiv_id=entry.get("arxiv_id"),
                title=entry.get("title"),
                url=entry.get("url"),
            ))

        if not sources:
            console.print(f"[yellow]No PDF found:[/yellow] {title}")
            continue

        best = sources[0]
        console.print(f"[green]Found:[/green] {title}")
        console.print(f"  Source: {best.source} ({best.version})")
        console.print(f"  URL: [dim]{best.url[:80]}[/dim]")

        if download:
            entry_dir = library.get_entry_dir(eid)
            dest = entry_dir / "document.pdf"
            with console.status("  Downloading..."):
                success = _run_async(_download_pdf(best.url, dest))
            if success:
                library.attach_file(eid, dest)
                console.print("  [green]Downloaded![/green]")
            else:
                # Try other sources
                downloaded = False
                for src in sources[1:]:
                    with console.status(f"  Trying {src.source}..."):
                        success = _run_async(_download_pdf(src.url, dest))
                    if success:
                        library.attach_file(eid, dest)
                        console.print(f"  [green]Downloaded from {src.source}![/green]")
                        downloaded = True
                        break
                if not downloaded:
                    console.print("  [red]Download failed from all sources[/red]")


@app.command()
def attach(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    files: list[Path] = typer.Argument(..., help="File(s) to attach"),
):
    """Attach files to an entry."""
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)
    for f in files:
        if not f.exists():
            console.print(f"[yellow]Skip:[/yellow] File not found: {f}"); continue
        library.attach_file(entry_id, f)
        console.print(f"[green]+[/green] {f.name}")


@app.command()
def detach(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    filenames: list[str] = typer.Argument(..., help="Filename(s) to detach"),
    force: bool = typer.Option(False, "--force", "-f"),
):
    """Remove attached files from an entry."""
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)
    for fname in filenames:
        fpath = entry_dir / fname
        if not fpath.exists():
            console.print(f"[yellow]Skip:[/yellow] {fname} not found"); continue
        if not force:
            if not typer.confirm(f"Delete file '{fname}'?"): continue
        fpath.unlink()
        # Update info.yaml
        entry = library.get_entry(entry_id)
        if entry:
            file_list = entry.get("files", [])
            if fname in file_list:
                file_list.remove(fname)
                library.update_entry(entry_id, {"files": file_list})
        console.print(f"[red]-[/red] {fname}")


# ─── CITATIONS ──────────────────────────────────────────────────────

@app.command()
def cite(
    entry_ids: list[str] = typer.Argument(..., help="Entry ID(s)"),
    style: str = typer.Option("apa", "--style", "-s", help="Citation style (apa, chicago-author-date, ieee, harvard-cite-them-right, nature, mla)"),
    bib: bool = typer.Option(False, "--bib", "-b", help="Output bibliography format instead of inline citation"),
):
    """Format citations. Pipe-friendly.

    suchi cite <id> --style apa
    suchi cite <id1> <id2> --style ieee --bib
    suchi cite <id> --style chicago-author-date | pbcopy
    """
    from .citations.processor import format_citation, format_bibliography

    entries = []
    for eid in entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            console.print(f"[red]Error:[/red] Entry not found: {eid}"); continue
        entries.append(entry)

    if not entries:
        raise typer.Exit(1)

    try:
        if bib:
            result = format_bibliography(entries, style)
            print(result)
        else:
            for entry in entries:
                result = format_citation(entry, style)
                print(result)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def styles():
    """List available citation styles."""
    from .citations.processor import list_styles
    for s in list_styles():
        out.print(f"  {s['id']:35s} {s['name']}")


# ─── EXPORT / IMPORT ───────────────────────────────────────────────

@app.command()
def export(
    entry_ids: Optional[list[str]] = typer.Argument(None, help="Entry IDs (omit for all)"),
    format: str = typer.Option("bibtex", "--format", "-f", help="bibtex, csl-json, or ris"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file (default: stdout)"),
):
    """Export references. Pipe-friendly: suchi export | pbcopy"""
    result = library.export_entries(entry_ids=entry_ids or None, fmt=format)
    if output:
        output.write_text(result)
        console.print(f"[green]Exported to:[/green] {output}")
    else:
        print(result)


@app.command(name="import")
def import_entries(
    file: Path = typer.Argument(..., help="BibTeX (.bib) file to import"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Tags for all imported entries"),
    collection: Optional[str] = typer.Option(None, "--collection", "-c"),
    json: bool = typer.Option(False, "--json"),
):
    """Import references from a BibTeX file."""
    if not file.exists():
        console.print(f"[red]Error:[/red] File not found: {file}"); raise typer.Exit(1)

    import re
    text = file.read_text()
    # Simple BibTeX parser — extract entries
    entries_raw = re.findall(r"@(\w+)\{([^,]+),([^@]*)\}", text, re.DOTALL)
    imported = []

    for entry_type, entry_key, fields_str in entries_raw:
        metadata = {"type": entry_type.lower(), "tags": list(tag), "collections": [collection] if collection else []}

        # Parse fields
        for match in re.finditer(r"(\w+)\s*=\s*\{([^}]*)\}", fields_str):
            key, val = match.group(1).lower(), match.group(2).strip()
            if key == "title": metadata["title"] = val
            elif key == "author":
                authors = []
                for a in val.split(" and "):
                    a = a.strip()
                    if "," in a:
                        parts = a.split(",", 1)
                        authors.append({"family": parts[0].strip(), "given": parts[1].strip()})
                    else:
                        parts = a.rsplit(" ", 1)
                        if len(parts) == 2: authors.append({"given": parts[0], "family": parts[1]})
                        else: authors.append({"family": a, "given": ""})
                metadata["author"] = authors
            elif key == "year": metadata["date"] = val
            elif key == "doi": metadata["doi"] = val
            elif key == "journal": metadata["journal"] = val
            elif key == "volume": metadata["volume"] = val
            elif key == "number": metadata["issue"] = val
            elif key == "pages": metadata["pages"] = val
            elif key == "publisher": metadata["publisher"] = val
            elif key == "abstract": metadata["abstract"] = val
            elif key == "url": metadata["url"] = val
            elif key == "isbn": metadata["isbn"] = val
            elif key == "keywords":
                kws = [k.strip().lower() for k in re.split(r"[,;]", val) if k.strip()]
                metadata["tags"] = list(dict.fromkeys(metadata.get("tags", []) + kws))

        if "title" in metadata:
            entry = library.add_entry_manual(metadata)
            imported.append(entry)

    if json:
        _print_json([_entry_summary(e) for e in imported])
    else:
        console.print(f"[green]Imported:[/green] {len(imported)} entries")
        for e in imported:
            console.print(f"  {e.get('title', '')[:60]}  [dim]{e['id']}[/dim]")


@app.command(name="import-zotero")
def import_zotero(
    file: Path = typer.Argument(..., help="Zotero RDF (.rdf) export file"),
    no_files: bool = typer.Option(False, "--no-files", help="Skip copying attached PDFs"),
    no_skip: bool = typer.Option(False, "--no-skip", help="Import duplicates instead of skipping"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Import a Zotero RDF library export.

    Export from Zotero: File → Export Library → Zotero RDF (with files if desired).
    This imports all items, collections (with hierarchy), tags, and attached PDFs.

    Examples:
        suchi import-zotero ~/Downloads/MyLibrary.rdf
        suchi import-zotero export.rdf --no-files
        suchi import-zotero export.rdf --json | jq
    """
    if not file.exists():
        console.print(f"[red]Error:[/red] File not found: {file}", err=True)
        raise typer.Exit(1)

    if not file.name.endswith(".rdf"):
        console.print("[yellow]Warning:[/yellow] File doesn't end with .rdf — continuing anyway", err=True)

    from .translators.zotero_rdf import import_rdf_to_library

    with console.status("Importing Zotero library..."):
        stats = import_rdf_to_library(
            file,
            copy_files=not no_files,
            skip_existing=not no_skip,
        )

    if json_out:
        _print_json(stats)
    else:
        console.print("[green]Import complete:[/green]")
        console.print(f"  Imported:    {stats['imported']}")
        console.print(f"  Skipped:     {stats['skipped']} (duplicates)")
        console.print(f"  Errors:      {stats['errors']}")
        console.print(f"  Collections: {stats['collections_created']} created")

        if stats['imported'] > 0:
            console.print("\n[dim]Run 'suchi list' to see your library.[/dim]")


# ─── UTILITY ────────────────────────────────────────────────────────

@app.command()
def stats(json: bool = typer.Option(False, "--json")):
    """Show library statistics."""
    entries = library.list_entries(limit=100_000)
    all_tags = library.get_all_tags()
    all_cols = col_service.get_collections_flat()

    total_files = sum(len(e.get("files", [])) for e in entries)
    with_pdf = sum(1 for e in entries if any(f.endswith(".pdf") for f in e.get("files", [])))
    with_abstract = sum(1 for e in entries if e.get("abstract"))

    years = {}
    for e in entries:
        y = (e.get("date", "") or "").split("-")[0]
        if y: years[y] = years.get(y, 0) + 1

    data = {
        "entries": len(entries),
        "with_pdf": with_pdf,
        "with_abstract": with_abstract,
        "total_files": total_files,
        "tags": len(all_tags),
        "collections": len(all_cols),
        "years": dict(sorted(years.items())),
        "library_path": str(get_config().library_dir),
    }

    if json:
        _print_json(data)
    else:
        out.print(f"  Entries:       {data['entries']}")
        out.print(f"  With PDF:      {data['with_pdf']}")
        out.print(f"  With abstract: {data['with_abstract']}")
        out.print(f"  Files:         {data['total_files']}")
        out.print(f"  Tags:          {data['tags']}")
        out.print(f"  Collections:   {data['collections']}")
        if years:
            out.print(f"  Years:         {', '.join(f'{y}({c})' for y, c in sorted(years.items()))}")
        out.print(f"  Library:       {data['library_path']}")


@app.command()
def reindex():
    """Rebuild the search index."""
    from .search import rebuild_index
    with console.status("Rebuilding index..."):
        count = rebuild_index()
    console.print(f"[green]Indexed:[/green] {count} entries")


@app.command(name="backfill-abstracts")
def backfill_abstracts(
    json_out: bool = typer.Option(False, "--json"),
):
    """Fetch missing abstracts from Semantic Scholar for all entries.

    Useful after importing from a source that doesn't include abstracts
    (like CrossRef for paywalled journals).

    Examples:
        suchi backfill-abstracts
        suchi backfill-abstracts --json | jq '.fixed'
    """
    entries = library.list_entries(limit=100_000)
    missing = [e for e in entries if not e.get("abstract") and e.get("doi")]

    if not missing:
        console.print("[green]All entries with DOIs already have abstracts.[/green]")
        return

    console.print(f"Found {len(missing)} entries missing abstracts. Fetching from Semantic Scholar...")

    fixed = []
    errors = 0

    for entry in missing:
        try:
            abstract = _run_async(_fetch_abstract(entry["doi"]))
            if abstract:
                library.update_entry(entry["id"], {"abstract": abstract})
                fixed.append(entry["id"])
                console.print(f"  [green]✓[/green] {entry.get('title', '')[:60]}")
            else:
                console.print(f"  [dim]✗ {entry.get('title', '')[:60]} (not available)[/dim]")
        except Exception:
            errors += 1

    if json_out:
        _print_json({"total_missing": len(missing), "fixed": len(fixed), "errors": errors})
    else:
        console.print(f"\n[green]Fixed:[/green] {len(fixed)}/{len(missing)} abstracts")
        if errors:
            console.print(f"[red]Errors:[/red] {errors}")


async def _fetch_abstract(doi: str) -> str | None:
    from .translators.semantic_scholar import get_abstract_by_doi
    return await get_abstract_by_doi(doi)


@app.command(name="backfill-dois")
def backfill_dois(
    limit: int = typer.Option(0, "--limit", "-n", help="Max entries to process (0 = all)"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find and fill in missing DOIs by searching CrossRef by title.

    Searches CrossRef for each entry that lacks a DOI, using the title.
    When a confident match is found, updates the entry with the DOI.
    Also backfills abstracts from Semantic Scholar for newly-DOI'd entries.

    Examples:
        suchi backfill-dois
        suchi backfill-dois --limit 50
        suchi backfill-dois --json | jq
    """
    entries = library.list_entries(limit=100_000)
    missing = [
        e for e in entries
        if (not e.get("doi") or len(str(e.get("doi", ""))) < 4)
        and e.get("title") and len(e["title"]) > 10
    ]

    if not missing:
        console.print("[green]All entries already have DOIs.[/green]")
        return

    if limit > 0:
        missing = missing[:limit]

    console.print(f"Found {len(missing)} entries without DOIs. Searching CrossRef...")

    found = 0
    not_found = 0
    errors = 0

    for i, entry in enumerate(missing):
        title = entry.get("title", "")
        # Clean title — remove journal name suffixes like "| Journal of X"
        clean_title = title.split("|")[0].strip()

        try:
            result = _run_async(_resolve_doi_by_title(clean_title, entry.get("author", [])))
            if result:
                doi = result.get("doi", "")
                updates = {"doi": doi}

                # Also grab abstract if we don't have one
                if not entry.get("abstract") and result.get("abstract"):
                    updates["abstract"] = result["abstract"]

                # Grab citation count
                if result.get("cited_by_count"):
                    updates["cited_by_count"] = result["cited_by_count"]

                library.update_entry(entry["id"], updates)
                found += 1
                console.print(f"  [green]✓[/green] {clean_title[:55]} → {doi}")
            else:
                not_found += 1
                if not json_out:
                    console.print(f"  [dim]· {clean_title[:55]} (not found)[/dim]")
        except Exception as e:
            errors += 1
            if not json_out:
                console.print(f"  [red]✗[/red] {clean_title[:55]}: {e}")

        # Rate limit: CrossRef polite pool is 50/sec, we go much slower
        if (i + 1) % 10 == 0 and not json_out:
            console.print(f"  [dim]... {i+1}/{len(missing)} processed[/dim]")

    if json_out:
        _print_json({"total_missing": len(missing), "found": found, "not_found": not_found, "errors": errors})
    else:
        console.print(f"\n[green]Done:[/green] {found} DOIs found, {not_found} not found, {errors} errors")


async def _resolve_doi_by_title(title: str, authors: list[dict]) -> dict | None:
    """Search CrossRef by title and verify author match before accepting."""
    from .translators.crossref import search_by_title as cr_search
    result = await cr_search(title)
    if not result:
        return None

    # Extra validation: if we have authors, check at least one surname matches
    if authors and result.get("author"):
        entry_surnames = {a.get("family", "").lower() for a in authors if a.get("family")}
        result_surnames = {a.get("family", "").lower() for a in result["author"] if a.get("family")}
        if entry_surnames and result_surnames and not (entry_surnames & result_surnames):
            return None  # No author overlap — likely a wrong match

    return result


@app.command()
def config():
    """Open config file in $EDITOR."""
    from .config import CONFIG_FILE
    cfg = get_config()
    cfg.save()  # Ensure file exists
    editor = cfg.editor or os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(CONFIG_FILE)])


@app.command()
def serve(
    port: int = typer.Option(9876, "--port", "-p"),
    host: str = typer.Option("127.0.0.1", "--host"),
):
    """Start the Suchi API server."""
    import uvicorn
    console.print(f"[green]Suchi server → {host}:{port}[/green]")
    uvicorn.run("suchi.api:app", host=host, port=port, reload=False)


# ─── AI CHAT ────────────────────────────────────────────────────────

@app.command()
def chat(
    entry_id: Optional[str] = typer.Option(None, "--paper", "-p", help="Chat about a specific paper"),
    collection_id: Optional[str] = typer.Option(None, "--collection", "-c", help="Chat about a collection"),
    question: Optional[str] = typer.Argument(None, help="One-shot question (omit for interactive mode)"),
):
    """Chat with AI about your papers.

    Interactive mode:
        suchi chat --paper <entry-id>
        suchi chat --collection <collection-id>
        suchi chat

    One-shot (pipe-friendly):
        suchi chat --paper <id> "Summarize this paper"
        suchi chat --collection <id> "What are the key themes?" | head -20
    """
    cfg = get_config()
    if not cfg.ai.gemini_api_key:
        console.print("[red]Error:[/red] Gemini API key not set. Run: suchi config")
        raise typer.Exit(1)

    # Build context description
    if entry_id:
        entry = library.get_entry(entry_id)
        if not entry:
            console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)
        context_label = f"paper: {entry.get('title', entry_id)[:50]}"
    elif collection_id:
        col = col_service.get_collection(collection_id)
        if not col:
            console.print(f"[red]Error:[/red] Collection not found: {collection_id}"); raise typer.Exit(1)
        context_label = f"collection: {col['name']}"
    else:
        context_label = "general"

    if question:
        # One-shot mode — print response to stdout and exit
        resp = _run_async(_chat_oneshot(question, entry_id=entry_id, collection_id=collection_id))
        print(resp)
        return

    # Interactive REPL mode
    console.print(f"[purple]AI Chat[/purple] [{context_label}]")
    console.print("[dim]Type your questions. Ctrl+D or 'exit' to quit.[/dim]\n")

    history: list[dict] = []
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            break

        history.append({"role": "user", "content": user_input})

        with console.status("[purple]Thinking...[/purple]"):
            resp = _run_async(_chat_oneshot(
                user_input, entry_id=entry_id, collection_id=collection_id, history=history[:-1]
            ))

        history.append({"role": "assistant", "content": resp})
        out.print(f"\n[bold purple]AI:[/bold purple] {resp}\n")


@app.command()
def ask(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    question: str = typer.Argument(..., help="Question about the paper"),
):
    """Quick one-shot question about a paper. Pipe-friendly.

    suchi ask <entry-id> "What is the main finding?"
    suchi ask <entry-id> "Summarize in 3 bullet points" | pbcopy
    """
    cfg = get_config()
    if not cfg.ai.gemini_api_key:
        console.print("[red]Error:[/red] Gemini API key not set. Run: suchi config")
        raise typer.Exit(1)

    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}"); raise typer.Exit(1)

    with console.status(f"[purple]Asking about: {entry.get('title', '')[:40]}...[/purple]"):
        resp = _run_async(_chat_oneshot(question, entry_id=entry_id))

    print(resp)


async def _chat_oneshot(
    message: str,
    entry_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    selected_text: Optional[str] = None,
    history: Optional[list[dict]] = None,
) -> str:
    """Send a single chat message and return the full response."""
    import httpx as hx

    cfg = get_config()
    api_key = cfg.ai.gemini_api_key
    model = cfg.ai.model or "gemini-2.5-flash"

    # Build context using the same logic as the API route
    from .routes.chat import _build_context, ChatRequest
    req = ChatRequest(
        message=message,
        entry_id=entry_id,
        collection_id=collection_id,
        selected_text=selected_text,
        history=[],
    )
    system_prompt, context_text = _build_context(req)

    contents = []
    if context_text:
        contents.append({"role": "user", "parts": [{"text": f"{system_prompt}\n\n---\n\n{context_text}"}]})
        contents.append({"role": "model", "parts": [{"text": "I've reviewed the material. How can I help?"}]})

    if history:
        for msg in history:
            contents.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [{"text": msg["content"]}]
            })

    contents.append({"role": "user", "parts": [{"text": message}]})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    async with hx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json={
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        })

        if resp.status_code != 200:
            return f"Error: {resp.text[:300]}"

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "Error: No response from Gemini"

        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


@app.command()
def index(
    entry_id: Optional[str] = typer.Argument(None, help="Entry ID to index (omit for --all or --collection)"),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Index all papers in a collection"),
    all_entries: bool = typer.Option(False, "--all", help="Index all papers in the library"),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild even if cached"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Build a PageIndex tree for papers (enables smart RAG chat).

    Creates a hierarchical table-of-contents tree via Gemini, enabling
    reasoning-based retrieval without vector embeddings.

    Inspired by VectifyAI/PageIndex (https://github.com/VectifyAI/PageIndex).

    Examples:
        suchi index my-paper-id
        suchi index --collection "Thesis References"
        suchi index --all
        suchi index my-paper-id --force
    """
    from .pageindex.indexer import build_tree_index, build_collection_index

    if entry_id:
        # Index a single paper
        entry = library.get_entry(entry_id)
        if not entry:
            console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
            raise typer.Exit(1)

        pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
        if not pdfs:
            console.print(f"[yellow]No PDF attached to {entry_id}[/yellow]")
            raise typer.Exit(1)

        entry_dir = library.get_entry_dir(entry_id)
        pdf_path = entry_dir / pdfs[0]

        with console.status(f"Building tree index for {entry.get('title', entry_id)[:50]}..."):
            tree = build_tree_index(pdf_path, force=force)

        sections = len(tree.get("tree", []))
        pages = tree.get("total_pages", 0)

        if json_out:
            _print_json(tree)
        else:
            console.print(f"[green]Indexed:[/green] {entry.get('title', entry_id)[:60]}")
            console.print(f"  {pages} pages → {sections} sections")

    elif collection:
        # Index all papers in a collection
        entries = library.list_entries(collection=collection, limit=100_000)
        if not entries:
            console.print(f"[yellow]No entries in collection: {collection}[/yellow]")
            raise typer.Exit(1)

        config = get_config()
        lib_dir = config.library_dir

        console.print(f"Indexing {len(entries)} papers in collection [bold]{collection}[/bold]...")
        indexed = 0
        for entry in entries:
            pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
            if not pdfs:
                continue
            entry_dir = library.get_entry_dir(entry["id"])
            pdf_path = entry_dir / pdfs[0]
            try:
                with console.status(f"  [{indexed+1}/{len(entries)}] {entry.get('title', '')[:50]}..."):
                    build_tree_index(pdf_path, force=force)
                indexed += 1
            except Exception as e:
                console.print(f"  [red]✗[/red] {entry.get('title', '')[:50]}: {e}")

        # Build collection-level meta-index
        with console.status("Building collection meta-index..."):
            col_index = build_collection_index(collection, entries, lib_dir, force=force)

        if json_out:
            _print_json(col_index)
        else:
            console.print(f"\n[green]Done:[/green] {indexed} papers indexed, collection meta-index built")

    elif all_entries:
        entries = library.list_entries(limit=100_000)
        with_pdfs = [e for e in entries if any(f.endswith(".pdf") for f in e.get("files", []))]

        console.print(f"Indexing {len(with_pdfs)} papers (with PDFs)...")
        indexed = 0
        errors = 0
        for i, entry in enumerate(with_pdfs):
            pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
            entry_dir = library.get_entry_dir(entry["id"])
            pdf_path = entry_dir / pdfs[0]
            try:
                with console.status(f"  [{i+1}/{len(with_pdfs)}] {entry.get('title', '')[:50]}..."):
                    build_tree_index(pdf_path, force=force)
                indexed += 1
            except Exception as e:
                errors += 1
                console.print(f"  [red]✗[/red] {entry.get('title', '')[:50]}: {e}")

        console.print(f"\n[green]Done:[/green] {indexed} indexed, {errors} errors")

    else:
        console.print("[red]Error:[/red] Provide an entry ID, --collection, or --all")
        raise typer.Exit(1)


@app.command(name="cited-by")
def cited_by(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    limit: int = typer.Option(10, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find papers that cite this one (downstream citations).

    Shows newer papers that build on, extend, or reference this work.
    Like Research Rabbit's "downstream" view.

    Examples:
        suchi cited-by kucsko-2013-nanometre-scale
        suchi cited-by my-paper --limit 20 --json | jq '.[].title'
    """
    from .translators.discovery import get_citing_papers
    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
        raise typer.Exit(1)
    doi = entry.get("doi")
    if not doi:
        console.print("[red]Error:[/red] No DOI for this entry. Discovery requires a DOI.")
        raise typer.Exit(1)

    with console.status("Finding citing papers..."):
        papers = _run_async(get_citing_papers(doi, limit=limit))

    if json_out:
        _print_json(papers)
        return

    if not papers:
        console.print("[dim]No citing papers found.[/dim]")
        return

    console.print(f"[bold]Papers citing:[/bold] {entry.get('title', '')[:60]}\n")
    for p in papers:
        authors = ", ".join(a.get("family", "") for a in p.get("author", [])[:3])
        cites = p.get("cited_by_count", 0)
        year = p.get("year", "?")
        doi_str = p.get("doi", "")
        console.print(f"  [bold]{p.get('title', '')[:70]}[/bold]")
        console.print(f"    {authors} ({year})  [amber]{cites} citations[/amber]")
        if doi_str:
            console.print(f"    DOI: [dim]{doi_str}[/dim]")
        console.print()


@app.command()
def related(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    limit: int = typer.Option(10, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find related/similar papers.

    Uses Semantic Scholar's recommendation engine. These papers may not
    directly cite each other but cover similar topics.

    Examples:
        suchi related kucsko-2013-nanometre-scale
        suchi related my-paper --json | jq '.[].doi'
    """
    from .translators.discovery import get_related_papers
    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
        raise typer.Exit(1)
    doi = entry.get("doi")
    if not doi:
        console.print("[red]Error:[/red] No DOI. Discovery requires a DOI.")
        raise typer.Exit(1)

    with console.status("Finding related papers..."):
        papers = _run_async(get_related_papers(doi, limit=limit))

    if json_out:
        _print_json(papers)
        return

    if not papers:
        console.print("[dim]No related papers found.[/dim]")
        return

    console.print(f"[bold]Related to:[/bold] {entry.get('title', '')[:60]}\n")
    for p in papers:
        authors = ", ".join(a.get("family", "") for a in p.get("author", [])[:3])
        cites = p.get("cited_by_count", 0)
        year = p.get("year", "?")
        console.print(f"  [bold]{p.get('title', '')[:70]}[/bold]")
        console.print(f"    {authors} ({year})  [amber]{cites} citations[/amber]")
        console.print()


@app.command(name="by-author")
def by_author(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    author: Optional[str] = typer.Option(None, "--author", "-a", help="Author name to search (default: first author)"),
    limit: int = typer.Option(10, "--limit", "-n"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Find more papers by the same author.

    Shows the author's most-cited papers. Defaults to the first author.
    Use --author to pick a specific co-author.

    Examples:
        suchi by-author kucsko-2013-nanometre-scale
        suchi by-author my-paper --author "Lukin"
        suchi by-author my-paper --json | jq '.papers[].title'
    """
    from .translators.discovery import get_author_papers
    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
        raise typer.Exit(1)
    doi = entry.get("doi")
    if not doi:
        console.print("[red]Error:[/red] No DOI. Discovery requires a DOI.")
        raise typer.Exit(1)

    with console.status("Finding author's papers..."):
        result = _run_async(get_author_papers(doi, author_name=author, limit=limit))

    if json_out:
        _print_json(result)
        return

    author_info = result.get("author", {})
    papers = result.get("papers", [])

    if author_info:
        console.print(f"[bold]{author_info.get('name', '?')}[/bold]")
        console.print(f"  Papers: {author_info.get('paper_count', '?')}  ·  Citations: {author_info.get('citation_count', '?')}  ·  h-index: {author_info.get('h_index', '?')}")
        console.print()

    if not papers:
        console.print("[dim]No papers found.[/dim]")
        return

    for p in papers:
        cites = p.get("cited_by_count", 0)
        year = p.get("year", "?")
        console.print(f"  [bold]{p.get('title', '')[:70]}[/bold]")
        console.print(f"    ({year})  [amber]{cites} citations[/amber]")
        console.print()


@app.command()
def discover(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Full discovery: citing papers + related works + same-author papers.

    Runs all discovery queries in parallel. Like Research Rabbit.

    Examples:
        suchi discover kucsko-2013-nanometre-scale
        suchi discover my-paper --json | jq '.citing | length'
    """
    from .translators.discovery import discover_all
    entry = library.get_entry(entry_id)
    if not entry:
        console.print(f"[red]Error:[/red] Entry not found: {entry_id}")
        raise typer.Exit(1)
    doi = entry.get("doi")
    if not doi:
        console.print("[red]Error:[/red] No DOI. Discovery requires a DOI.")
        raise typer.Exit(1)

    with console.status("Discovering related papers..."):
        results = _run_async(discover_all(doi))

    if json_out:
        _print_json(results)
        return

    console.print(f"[bold]Discovery for:[/bold] {entry.get('title', '')[:60]}\n")

    citing = results.get("citing", [])
    related = results.get("related", [])
    author_data = results.get("author", {})
    author_papers = author_data.get("papers", [])

    console.print(f"[bold green]▸ Citing this paper ({len(citing)})[/bold green]")
    for p in citing[:5]:
        year = p.get("year", "?")
        cites = p.get("cited_by_count", 0)
        console.print(f"  {p.get('title', '')[:65]} ({year}, {cites} cites)")
    if len(citing) > 5:
        console.print(f"  [dim]... and {len(citing) - 5} more[/dim]")

    console.print(f"\n[bold blue]▸ Related papers ({len(related)})[/bold blue]")
    for p in related[:5]:
        year = p.get("year", "?")
        cites = p.get("cited_by_count", 0)
        console.print(f"  {p.get('title', '')[:65]} ({year}, {cites} cites)")

    author_info = author_data.get("author", {})
    aname = author_info.get("name", "?") if author_info else "?"
    console.print(f"\n[bold yellow]▸ More by {aname} ({len(author_papers)})[/bold yellow]")
    for p in author_papers[:5]:
        year = p.get("year", "?")
        cites = p.get("cited_by_count", 0)
        console.print(f"  {p.get('title', '')[:65]} ({year}, {cites} cites)")

    console.print("\n[dim]Use --json for full results, or suchi cited-by / related / by-author for individual queries.[/dim]")


if __name__ == "__main__":
    app()
