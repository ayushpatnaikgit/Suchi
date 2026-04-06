"""OpenLibrary API translator for ISBN resolution."""

import httpx


OPENLIBRARY_API = "https://openlibrary.org/api/books"


async def resolve_isbn(isbn: str) -> dict | None:
    """Resolve an ISBN to bibliographic metadata via OpenLibrary."""
    isbn = isbn.replace("-", "").replace(" ", "").strip()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            OPENLIBRARY_API,
            params={
                "bibkeys": f"ISBN:{isbn}",
                "format": "json",
                "jscmd": "data",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        key = f"ISBN:{isbn}"
        if key not in data:
            return None
        book = data[key]

    authors = []
    for a in book.get("authors", []):
        name = a.get("name", "")
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            authors.append({"given": parts[0], "family": parts[1]})
        else:
            authors.append({"given": "", "family": name})

    publishers = book.get("publishers", [])
    publisher = publishers[0].get("name") if publishers else None

    return {
        "type": "book",
        "title": book.get("title", ""),
        "author": authors,
        "isbn": isbn,
        "date": book.get("publish_date"),
        "publisher": publisher,
        "pages": str(book.get("number_of_pages", "")) or None,
        "url": book.get("url"),
    }
