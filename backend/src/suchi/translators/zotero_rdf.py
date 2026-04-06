"""Import a Zotero RDF export into Suchi.

Zotero RDF uses RDF/XML with these namespaces:
- z:       http://www.zotero.org/namespaces/export#  (itemType, collections)
- dc:      http://purl.org/dc/elements/1.1/           (title, subject/tags, date, publisher)
- dcterms: http://purl.org/dc/terms/                   (abstract, isPartOf)
- bib:     http://purl.org/net/biblio#                 (types: Article, Book, Thesis...)
- foaf:    http://xmlns.com/foaf/0.1/                  (Person: surname, givenName)
- prism:   http://prismstandard.org/namespaces/1.2/basic/  (volume, number, doi)
- link:    http://purl.org/rss/1.0/modules/link/       (attachments)
"""

import re
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import Generator

NS = {
    "rdf":     "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "bib":     "http://purl.org/net/biblio#",
    "foaf":    "http://xmlns.com/foaf/0.1/",
    "prism":   "http://prismstandard.org/namespaces/1.2/basic/",
    "z":       "http://www.zotero.org/namespaces/export#",
    "link":    "http://purl.org/rss/1.0/modules/link/",
    "vcard":   "http://nwalsh.com/rdf/vCard#",
}


def _tag(ns: str, name: str) -> str:
    return f"{{{NS[ns]}}}{name}"


def _text(el: ET.Element | None) -> str:
    """Get text content of an element, or '' if None."""
    return (el.text or "").strip() if el is not None else ""


def _find_text(parent: ET.Element, ns: str, name: str) -> str:
    return _text(parent.find(_tag(ns, name)))


# Type mapping: bib:Article → "article", bib:Book → "book", etc.
TYPE_MAP = {
    f"{NS['bib']}Article": "article",
    f"{NS['bib']}Book": "book",
    f"{NS['bib']}BookSection": "inbook",
    f"{NS['bib']}Thesis": "thesis",
    f"{NS['bib']}Report": "report",
    f"{NS['bib']}Letter": "letter",
    f"{NS['bib']}Manuscript": "manuscript",
    f"{NS['bib']}Patent": "patent",
    f"{NS['bib']}Legislation": "legislation",
    f"{NS['bib']}ConferenceProceedings": "inproceedings",
    f"{NS['bib']}Document": "article",
    f"{NS['bib']}Recording": "recording",
    f"{NS['bib']}Image": "image",
    f"{NS['bib']}MotionPicture": "film",
    f"{NS['bib']}Illustration": "artwork",
    f"{NS['bib']}Interview": "interview",
    f"{NS['bib']}Memo": "note",
    f"{NS['bib']}Data": "dataset",
    f"{NS['z']}Attachment": "attachment",
}


def parse_rdf(rdf_path: Path) -> dict:
    """Parse a Zotero RDF export file.

    Returns:
        {
            "items": [...],         # List of parsed items (papers, books, etc.)
            "collections": [...],   # List of collections with hierarchy
            "attachments": {...},   # Map of resource URI → attachment info
        }
    """
    tree = ET.parse(str(rdf_path))
    root = tree.getroot()

    # First pass: index all resources by their rdf:about URI
    resource_map: dict[str, ET.Element] = {}
    for child in root:
        about = child.get(_tag("rdf", "about")) or child.get("rdf:about")
        if about:
            resource_map[about] = child

    # Parse collections
    collections = _parse_collections(root, resource_map)

    # Parse attachments (files linked to items)
    attachments = _parse_attachments(root, resource_map, rdf_path.parent)

    # Parse items
    items = list(_parse_items(root, resource_map, collections, attachments))

    return {
        "items": items,
        "collections": collections,
        "attachments": attachments,
    }


def _parse_collections(root: ET.Element, resource_map: dict) -> list[dict]:
    """Parse z:Collection elements into a flat list with parent_id."""
    collections = []
    z_collection_tag = _tag("z", "Collection")

    for el in root:
        # Zotero RDF uses the element tag itself as the type
        if el.tag != z_collection_tag:
            continue

        col_id = el.get(_tag("rdf", "about")) or el.get("rdf:about") or ""
        name = _find_text(el, "dc", "title")
        collections.append({
            "id": col_id,
            "name": name,
            "children_uris": [],
            "item_uris": [],
        })
        # Get hasPart children
        for has_part in el.findall(_tag("dcterms", "hasPart")):
            ref = has_part.get(_tag("rdf", "resource")) or ""
            if ref.startswith("#collection_"):
                collections[-1]["children_uris"].append(ref)
            else:
                collections[-1]["item_uris"].append(ref)

    return collections


def _parse_attachments(root: ET.Element, resource_map: dict, base_dir: Path) -> dict[str, dict]:
    """Parse z:Attachment elements."""
    attachments: dict[str, dict] = {}
    z_attachment_tag = _tag("z", "Attachment")

    for el in root:
        if el.tag != z_attachment_tag:
            continue

        uri = el.get(_tag("rdf", "about")) or el.get("rdf:about") or ""

        # Get file path — Zotero RDF stores it in several possible places:
        # 1. z:path element with rdf:resource attribute (most common in exports)
        # 2. link:link element with rdf:resource attribute
        # 3. dc:identifier
        file_path = None

        # Check z:path (primary location for exported files)
        path_el = el.find(_tag("z", "path"))
        if path_el is not None:
            href = path_el.get(_tag("rdf", "resource")) or path_el.text or ""
            href = href.strip()
            if href:
                if href.startswith("file://"):
                    file_path = href[7:]
                elif href.startswith("files/"):
                    file_path = str(base_dir / href)
                elif not href.startswith("http"):
                    file_path = str(base_dir / href)

        # Check link:link as fallback
        if not file_path:
            link_el = el.find(_tag("link", "link"))
            if link_el is not None:
                href = link_el.get(_tag("rdf", "resource")) or ""
                if href:
                    if href.startswith("file://"):
                        file_path = href[7:]
                    elif href.startswith("files/"):
                        file_path = str(base_dir / href)
                    elif not href.startswith("http"):
                        file_path = href

        # Check dc:identifier as last resort
        if not file_path:
            identifier = _find_text(el, "dc", "identifier")
            if identifier:
                if identifier.startswith("file://"):
                    file_path = identifier[7:]
                elif "/" in identifier and not identifier.startswith("http"):
                    file_path = str(base_dir / identifier)

        title = _find_text(el, "dc", "title")
        mime = _find_text(el, "z", "type") or _find_text(el, "link", "type")

        attachments[uri] = {
            "title": title,
            "path": file_path,
            "mime_type": mime,
        }

    return attachments


def _parse_items(
    root: ET.Element,
    resource_map: dict,
    collections: list[dict],
    attachments: dict[str, dict],
) -> Generator[dict, None, None]:
    """Parse item resources into Suchi metadata dicts."""

    # Build item URI → collection mapping
    uri_to_collections: dict[str, list[str]] = {}
    for col in collections:
        for item_uri in col.get("item_uris", []):
            uri_to_collections.setdefault(item_uri, []).append(col["name"])

    for el in root:
        # Determine type from the element tag itself (e.g., bib:Article, bib:Book)
        # Zotero RDF uses the tag name as the type, NOT an rdf:type child element.
        el_tag = el.tag  # e.g., "{http://purl.org/net/biblio#}Article"

        item_type = TYPE_MAP.get(el_tag, "")

        # Also check z:itemType for more specific type (e.g., "journalArticle")
        z_type = _find_text(el, "z", "itemType")
        if z_type:
            item_type = _map_zotero_type(z_type)

        # Skip collections, attachments, notes, and unknown types
        if not item_type or item_type in ("note", "attachment"):
            continue

        uri = el.get(_tag("rdf", "about")) or el.get("rdf:about") or ""

        # Title
        title = _find_text(el, "dc", "title")
        if not title:
            continue  # Skip items without titles

        # Authors
        authors = _parse_creators(el)

        # Date
        date = _find_text(el, "dc", "date") or _find_text(el, "dcterms", "dateSubmitted")

        # Abstract
        abstract = _find_text(el, "dcterms", "abstract")

        # DOI
        doi = _find_text(el, "dc", "identifier")
        if doi and not doi.startswith("10."):
            # Try extracting DOI from identifier
            doi_match = re.search(r"10\.\d{4,9}/[^\s]+", doi)
            doi = doi_match.group() if doi_match else None
        # Also check prism:doi
        prism_doi = _find_text(el, "prism", "doi")
        if prism_doi:
            doi = prism_doi

        # URL
        url = _find_text(el, "dc", "identifier")
        if url and not url.startswith("http"):
            url = None

        # Tags (dc:subject)
        tags = []
        for subj in el.findall(_tag("dc", "subject")):
            # Tags can be plain text or resources
            if subj.text and subj.text.strip():
                tags.append(subj.text.strip())
            else:
                # Check for rdf:value inside (automatic tags)
                val = subj.find(f".//{_tag('rdf', 'value')}")
                if val is not None and val.text:
                    tags.append(val.text.strip())

        # Journal/container
        journal = _find_container_title(el)

        # Volume, issue, pages
        volume = _find_text(el, "prism", "volume")
        issue = _find_text(el, "prism", "number")
        pages = _find_text(el, "bib", "pages")

        # Publisher
        publisher = _find_publisher(el)

        # ISBN/ISSN
        isbn = _find_text(el, "dc", "identifier")
        if isbn and not re.match(r"^[\d\-X]{10,17}$", isbn):
            isbn = None

        # Collections this item belongs to
        item_collections = uri_to_collections.get(uri, [])

        # Attached files — check both dcterms:hasPart and link:link
        item_files = []
        seen_refs = set()

        for has_part in el.findall(_tag("dcterms", "hasPart")):
            ref = has_part.get(_tag("rdf", "resource")) or ""
            if ref and ref in attachments and ref not in seen_refs:
                att = attachments[ref]
                if att.get("path"):
                    item_files.append(att)
                    seen_refs.add(ref)

        # link:link refs point to attachments in Zotero RDF exports
        for link_el in el.findall(_tag("link", "link")):
            ref = link_el.get(_tag("rdf", "resource")) or ""
            if ref and ref not in seen_refs:
                if ref in attachments:
                    att = attachments[ref]
                    if att.get("path"):
                        item_files.append(att)
                        seen_refs.add(ref)

        yield {
            "type": item_type,
            "title": title,
            "author": authors,
            "date": date or None,
            "abstract": abstract or None,
            "doi": doi,
            "url": url,
            "tags": tags,
            "collections": item_collections,
            "journal": journal or None,
            "volume": volume or None,
            "issue": issue or None,
            "pages": pages or None,
            "publisher": publisher or None,
            "isbn": isbn,
            "files": item_files,
            "_uri": uri,
        }


def _parse_creators(el: ET.Element) -> list[dict]:
    """Parse foaf:Person creators from an item element."""
    authors = []

    # Creators are typically in bib:authors or dc:creator sequences
    for creator_container_tag in ["authors", "editors", "contributors", "translators"]:
        container = el.find(_tag("bib", creator_container_tag))
        if container is not None:
            # It's usually a rdf:Seq containing rdf:li elements
            seq = container.find(_tag("rdf", "Seq"))
            if seq is not None:
                for li in seq.findall(_tag("rdf", "li")):
                    person = li.find(_tag("foaf", "Person"))
                    if person is None:
                        person = li  # Sometimes the Person is the li itself
                    surname = _find_text(person, "foaf", "surname")
                    given = _find_text(person, "foaf", "givenName") or _find_text(person, "foaf", "givenname")
                    if surname:
                        authors.append({"family": surname, "given": given})

    # Also check dc:creator (sometimes used for simpler exports)
    if not authors:
        for dc_creator in el.findall(_tag("dc", "creator")):
            person = dc_creator.find(_tag("foaf", "Person"))
            if person is not None:
                surname = _find_text(person, "foaf", "surname")
                given = _find_text(person, "foaf", "givenName") or _find_text(person, "foaf", "givenname")
                if surname:
                    authors.append({"family": surname, "given": given})

    return authors


def _find_container_title(el: ET.Element) -> str | None:
    """Find the journal/book/container title via dcterms:isPartOf chain."""
    for is_part in el.findall(_tag("dcterms", "isPartOf")):
        # The container can be a nested element or a reference
        container = is_part
        # Check for nested element with dc:title
        title = _find_text(container, "dc", "title")
        if title:
            return title
        # Check children for containers
        for child in container:
            title = _find_text(child, "dc", "title")
            if title:
                return title
    return None


def _find_publisher(el: ET.Element) -> str | None:
    """Find publisher via dc:publisher → foaf:Organization → foaf:name."""
    pub = el.find(_tag("dc", "publisher"))
    if pub is not None:
        org = pub.find(_tag("foaf", "Organization"))
        if org is not None:
            name = _find_text(org, "foaf", "name")
            if name:
                return name
        # Simple text publisher
        if pub.text and pub.text.strip():
            return pub.text.strip()
    return None


def _map_zotero_type(z_type: str) -> str:
    """Map Zotero item type string to our type."""
    mapping = {
        "journalArticle": "article",
        "book": "book",
        "bookSection": "inbook",
        "conferencePaper": "inproceedings",
        "thesis": "thesis",
        "report": "report",
        "webpage": "webpage",
        "patent": "patent",
        "film": "film",
        "artwork": "artwork",
        "computerProgram": "software",
        "preprint": "article",
        "magazineArticle": "article",
        "newspaperArticle": "article",
        "blogPost": "article",
        "encyclopediaArticle": "article",
        "dictionaryEntry": "article",
        "letter": "letter",
        "manuscript": "manuscript",
        "presentation": "presentation",
        "note": "note",
        "attachment": "attachment",
    }
    return mapping.get(z_type, "article")


def import_rdf_to_library(
    rdf_path: Path,
    copy_files: bool = True,
    skip_existing: bool = True,
) -> dict:
    """Import a Zotero RDF export into the Suchi library.

    Args:
        rdf_path: Path to the .rdf file
        copy_files: Whether to copy attached PDFs into the library
        skip_existing: Skip items that already exist (by DOI or title match)

    Returns:
        {"imported": int, "skipped": int, "errors": int, "collections_created": int}
    """
    from .. import library
    from .. import collections as col_service

    parsed = parse_rdf(rdf_path)

    stats = {"imported": 0, "skipped": 0, "errors": 0, "collections_created": 0}

    # Create collections first
    col_name_to_id: dict[str, str] = {}
    existing_collections = col_service.get_collections_flat()
    existing_col_names = {c["name"].lower(): c["id"] for c in existing_collections}

    for col in parsed["collections"]:
        name = col["name"]
        if name.lower() in existing_col_names:
            col_name_to_id[col["id"]] = existing_col_names[name.lower()]
        else:
            # Find parent
            parent_id = None
            for other_col in parsed["collections"]:
                if col["id"] in other_col.get("children_uris", []):
                    parent_id = col_name_to_id.get(other_col["id"])
                    break
            new_col = col_service.create_collection(name, parent_id=parent_id)
            col_name_to_id[col["id"]] = new_col["id"]
            stats["collections_created"] += 1

    # Build lookup for existing library items
    existing_entries = library.list_entries(limit=100_000)
    existing_dois = {e.get("doi", "").lower() for e in existing_entries if e.get("doi")}
    existing_titles = {e.get("title", "").lower().strip() for e in existing_entries}

    # Import items
    for item in parsed["items"]:
        try:
            # Check for duplicates
            if skip_existing:
                if item.get("doi") and item["doi"].lower() in existing_dois:
                    stats["skipped"] += 1
                    continue
                if item.get("title", "").lower().strip() in existing_titles:
                    stats["skipped"] += 1
                    continue

            # Map collection names to our collection IDs
            mapped_collections = []
            for col_name in item.get("collections", []):
                for rdf_id, our_id in col_name_to_id.items():
                    for col in parsed["collections"]:
                        if col["id"] == rdf_id and col["name"] == col_name:
                            mapped_collections.append(our_id)
                            break

            metadata = {
                "type": item["type"],
                "title": item["title"],
                "author": item["author"],
                "date": item.get("date"),
                "abstract": item.get("abstract"),
                "doi": item.get("doi"),
                "url": item.get("url"),
                "tags": item.get("tags", []),
                "collections": mapped_collections,
                "journal": item.get("journal"),
                "volume": item.get("volume"),
                "issue": item.get("issue"),
                "pages": item.get("pages"),
                "publisher": item.get("publisher"),
                "isbn": item.get("isbn"),
            }
            # Remove None values
            metadata = {k: v for k, v in metadata.items() if v is not None}

            entry = library.add_entry_manual(metadata)

            # Copy attached files
            if copy_files and item.get("files"):
                for file_info in item["files"]:
                    file_path = file_info.get("path")
                    if file_path:
                        src = Path(file_path)
                        if not src.exists():
                            # Try relative to the RDF file
                            src = rdf_path.parent / file_path
                        if src.exists() and src.is_file():
                            library.attach_file(entry["id"], src)

            stats["imported"] += 1

        except Exception as e:
            stats["errors"] += 1

    return stats
