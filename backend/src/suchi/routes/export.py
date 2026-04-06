"""Export/import routes."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import PlainTextResponse

from .. import library
from ..models import ExportRequest

router = APIRouter(prefix="/api", tags=["export"])


@router.post("/export")
def export_entries(data: ExportRequest):
    output = library.export_entries(
        entry_ids=data.entry_ids or None,
        fmt=data.format,
    )
    media_type = {
        "bibtex": "application/x-bibtex",
        "csl-json": "application/json",
        "ris": "application/x-research-info-systems",
    }.get(data.format, "text/plain")
    return PlainTextResponse(output, media_type=media_type)


@router.post("/import/zotero-rdf")
async def import_zotero_rdf(
    file: UploadFile = File(...),
    copy_files: bool = False,  # Can't copy files via API — no access to local filesystem paths
    skip_existing: bool = True,
):
    """Import a Zotero RDF export file.

    Upload the .rdf file. Attached PDFs cannot be imported via API (use the CLI for that).
    """
    from ..translators.zotero_rdf import import_rdf_to_library

    with tempfile.NamedTemporaryFile(suffix=".rdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        stats = import_rdf_to_library(
            tmp_path,
            copy_files=False,  # API uploads can't reference local files
            skip_existing=skip_existing,
        )
        return stats
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
