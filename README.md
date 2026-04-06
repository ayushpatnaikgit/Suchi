<p align="center">
  <img src="assets/logo.png" alt="[SUCHI]" width="280">
</p>
<p align="center">
  <strong>CLI-first reference manager with AI-powered research tools</strong>
</p>
<p align="center">
  Unix philosophy meets academic research. No Electron. No vendor lock-in. Your papers, your filesystem.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#cli-commands">CLI Commands</a> ·
  <a href="#features">Features</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

**Suchi** (सूची, Sanskrit for "index" or "catalog") is a reference manager built on Unix principles: everything is a file, every operation has a CLI command, and the GUI is a thin layer on top.

Your library is a directory of YAML files and PDFs — no proprietary database, no cloud dependency, no lock-in. Sync with Google Drive, chat with your papers using AI, and manage everything from the terminal.

## Why Suchi?

| Problem with Zotero/Mendeley | Suchi's approach |
|------------------------------|------------------|
| SQLite database — can't sync with cloud storage | **YAML files** — one directory per paper, safe to sync anywhere |
| GUI-first — can't script or automate | **CLI-first** — every feature is a command, pipe-friendly |
| Limited AI features | **Built-in AI chat** with PageIndex RAG — chat with papers, collections, selected text |
| Closed metadata extraction | **Multi-source resolution** — CrossRef, OpenAlex, Semantic Scholar, arXiv, OpenLibrary |
| Vendor lock-in | **Open formats** — YAML metadata, standard PDFs, BibTeX/CSL-JSON/RIS export |

## Installation

### Desktop App (recommended for most users)

Download the latest release for your platform:

| Platform | Download |
|----------|----------|
| **macOS** | [Suchi.dmg](https://github.com/ayushpatnaikgit/Suchi/releases) |
| **Windows** | [Suchi-Setup.exe](https://github.com/ayushpatnaikgit/Suchi/releases) |
| **Linux** | [Suchi.AppImage](https://github.com/ayushpatnaikgit/Suchi/releases) |

The desktop app bundles everything — no Python or Node.js needed.

### CLI Only (pip)

```bash
pip install suchi
suchi --help
```

### From Source (developers)

**Requirements:** Python 3.11+, Node.js 18+, Rust (for desktop builds)

```bash
git clone git@github.com:ayushpatnaikgit/Suchi.git
cd Suchi
./setup.sh    # installs backend + frontend + creates config
```

### Running

```bash
# CLI only — no server needed
suchi add 10.1038/nature12373
suchi search "machine learning"

# Web UI — start both servers
make dev
# → Backend:  http://127.0.0.1:9876
# → Frontend: http://localhost:5173

# Desktop app (Tauri)
cd src-tauri && cargo tauri dev

# Or just the API server
suchi serve
```

## Quick Start

```bash
# Add your first paper (by DOI)
suchi add 10.1038/nature12373

# Add by arXiv ID
suchi add 2301.07041

# Upload a PDF (extracts metadata automatically)
suchi add --pdf ~/Downloads/paper.pdf

# List your library
suchi list

# Search
suchi search "machine learning"

# Chat with a paper (requires Gemini API key)
suchi config set ai.gemini_api_key YOUR_KEY
suchi ask my-paper-id "What methods did they use?"

# Build a PageIndex for smarter RAG
suchi index my-paper-id

# Export to BibTeX
suchi export --format bibtex > references.bib

# Start the web UI
suchi serve
# Open http://localhost:9876 in your browser
```

## CLI Commands

Suchi follows Unix philosophy: each command does one thing well, outputs are pipe-friendly, and `--json` is available everywhere.

### Core
```bash
suchi add <DOI|ISBN|arXiv|URL>     # Add by identifier
suchi add --pdf <file.pdf>          # Add from PDF (auto-extracts metadata)
suchi add --manual                  # Interactive entry
suchi list [--tag TAG] [--json]     # List entries
suchi search <query>                # Full-text + fuzzy search (Tantivy + RapidFuzz)
suchi info <entry-id>               # Show detailed metadata
suchi edit <entry-id>               # Open info.yaml in $EDITOR
suchi open <entry-id>               # Open PDF in default viewer
suchi remove <entry-id>             # Delete entry
```

### Tags & Collections
```bash
suchi tag <entry-id> --add ml,transformers
suchi tag <entry-id> --remove old-tag
suchi collection create "Thesis/Chapter 1"
suchi collection list [--tree]
suchi collection add <entry-id> "Thesis/Chapter 1"
suchi collection merge "Old Name" "New Name"
```

### Export & Import
```bash
suchi export --format bibtex > refs.bib
suchi export --format csl-json > refs.json
suchi export --format ris > refs.ris
suchi import-zotero ~/Downloads/MyLibrary.rdf   # Import Zotero library
suchi cite <entry-id> --style apa               # Formatted citation
```

### AI Chat
```bash
suchi ask <entry-id> "What are the key findings?"     # Chat with a paper
suchi ask --collection "Thesis" "Compare methodologies" # Chat with a collection
suchi chat <entry-id>                                   # Interactive chat session
suchi index <entry-id>                                  # Build PageIndex tree
suchi index --collection "Thesis"                       # Index a collection
suchi index --all                                       # Index entire library
```

### Utilities
```bash
suchi find-pdf <entry-id>           # Find and download PDF from open access
suchi backfill-abstracts            # Fetch missing abstracts
suchi serve [--port 9876]           # Start API server + web UI
suchi config show                   # Show current config
suchi config set ai.gemini_api_key KEY
```

## Features

### Metadata Resolution Chain

When you add a paper, Suchi tries multiple sources to get the best metadata:

```
DOI → CrossRef API (free, no auth)
      ↓ fallback
arXiv ID → arXiv API
      ↓ fallback
ISBN → OpenLibrary API
      ↓ fallback
Title → OpenAlex (250M+ works) → CrossRef title search → Semantic Scholar
      ↓ fallback
PDF text → Extract DOI/arXiv/title from first pages → resolve above
```

Each source contributes different data: CrossRef has citation counts, OpenAlex has topic tags, Semantic Scholar has abstracts, arXiv has categories and OA PDFs.

### PageIndex RAG (Vectorless, Reasoning-Based Retrieval)

Inspired by [VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex). Instead of vector embeddings, Suchi uses LLM reasoning over document structure:

1. **Index**: Gemini analyzes your PDF and generates a hierarchical tree (sections, subsections, page ranges, summaries)
2. **Retrieve**: When you ask a question, the LLM reasons over the tree to find relevant sections — not similarity, but *relevance*
3. **Answer**: Only the relevant pages are sent as context, with page-level citations

```bash
# Build the tree index (done once per paper)
$ suchi index kucsko-2013-nanometre-scale-thermometry
Indexed: Nanometre-scale thermometry in a living cell
  22 pages → 9 sections

# Now chat uses smart retrieval instead of dumping the whole paper
$ suchi ask kucsko-2013 "What experimental setup did they use?"
The experimental setup utilized a confocal microscope equipped with
two independent excitation/collection paths... (on page 9)
```

For collections, Suchi builds a meta-index across papers and does two-level reasoning: first picks relevant papers, then picks relevant sections.

### Reference Extraction & Resolution

Click "References" on any paper to see its bibliography extracted and enriched:

- **Regex parser** handles IEEE, APA, Nature/Science, Chicago, and author-date formats
- Each reference is resolved via **OpenAlex → CrossRef → Semantic Scholar** for full metadata
- Shows **citation counts**, abstracts, tags, and DOIs
- **"Add to Library"** button adds the reference to the same collection as the parent paper
- Results are **cached to disk** — first load takes ~30s, subsequent loads are instant

### Search (Tantivy + RapidFuzz)

- **Tantivy** (Rust-based full-text index) for fast content search across titles, abstracts, and PDF text
- **RapidFuzz** for fuzzy matching — handles typos in author names and partial title matches
- **Faceted filtering** by year, author, tag, collection, journal
- Rebuilt automatically on entry changes

### Citation Formatting (10,000+ Styles)

```bash
$ suchi cite kucsko-2013 --style apa
Kucsko, G., Maurer, P. C., Yao, N. Y., et al. (2013). Nanometre-scale
thermometry in a living cell. Nature, 500(7460), 54-58.

$ suchi cite kucsko-2013 --style ieee
[1] G. Kucsko et al., "Nanometre-scale thermometry in a living cell,"
Nature, vol. 500, no. 7460, pp. 54-58, 2013.
```

Powered by **citeproc-py** with CSL styles: APA, Chicago, Harvard, IEEE, MLA, Nature, Elsevier Harvard, and more.

### Web UI

A React + TypeScript frontend with:
- Three-pane layout (sidebar → entry list → reading pane)
- Built-in PDF viewer with dark mode
- Drag-and-drop PDF upload
- Hierarchical collection tree with drag-to-organize
- Right-click context menu on entries
- Floating AI chat bubble (context-aware)
- Dark mode with persistence
- Reference popup with "Add to Library"

## Architecture

```
~/.config/suchi/config.yaml          # Configuration
~/Documents/Suchi Library/           # Your library (just a directory!)
├── einstein-1905-relativity/
│   ├── info.yaml                    # Metadata (human-editable!)
│   ├── document.pdf                 # The paper
│   ├── notes.md                     # Your notes
│   ├── .pageindex.json              # PageIndex tree (auto-generated)
│   ├── .references-cache.json       # Enriched references (cached)
│   └── annotations.yaml            # Highlights & annotations
├── collections.yaml                 # Collection hierarchy
└── .tantivy-index/                  # Search index (auto-rebuilt)
```

### Stack

| Layer | Technology |
|-------|-----------|
| **CLI** | Python + Typer |
| **API** | FastAPI + Uvicorn |
| **Frontend** | React + TypeScript + Tailwind CSS |
| **PDF** | PyMuPDF (extraction) + react-pdf (viewing) |
| **Search** | Tantivy (full-text) + RapidFuzz (fuzzy) |
| **AI** | Google Gemini API |
| **Citations** | citeproc-py + CSL styles |
| **Data** | YAML files (no database!) |

### Why No Database?

SQLite + cloud sync = database corruption. Suchi uses one YAML file per entry in a directory structure, which means:
- **Safe cloud sync** — each file is independent, no lock contention
- **Human-editable** — open any `info.yaml` in a text editor
- **Git-friendly** — track changes, branch, merge your library
- **Scriptable** — `grep`, `sed`, `awk` work on your library

### API Resolution Sources

| Source | Auth | Rate Limit | Used For |
|--------|------|------------|----------|
| CrossRef | Free, no key | 50 req/sec | DOI resolution, citation counts, title search |
| OpenAlex | Free, no key | 10k/day | Rich metadata, topic tags, OA PDF links |
| Semantic Scholar | Free, no key | 100/5min | Abstracts, paper search |
| arXiv | Free, no key | Unlimited | arXiv papers, categories |
| OpenLibrary | Free, no key | Unlimited | ISBN/book resolution |

## Development

```bash
# Clone
git clone git@github.com:ayushpatnaikgit/Suchi.git
cd Suchi

# Backend
cd backend
pip install -e ".[dev]"
suchi serve  # API on :9876

# Frontend (separate terminal)
cd frontend
npm install
npm run dev  # Vite on :5173

# Run tests
cd backend && pytest
```

### Project Structure

```
Suchi/
├── backend/                     # Python package
│   ├── pyproject.toml
│   └── src/suchi/
│       ├── cli.py               # Typer CLI (1200 lines)
│       ├── api.py               # FastAPI app
│       ├── library.py           # Entry CRUD on filesystem
│       ├── search.py            # Tantivy + RapidFuzz search engine
│       ├── collections.py       # Hierarchical collection tree
│       ├── config.py            # YAML config management
│       ├── pageindex/           # PageIndex RAG (vectorless retrieval)
│       │   ├── indexer.py       # Tree index builder via Gemini
│       │   └── retriever.py     # Reasoning-based page retrieval
│       ├── translators/         # Metadata resolution
│       │   ├── crossref.py      # CrossRef API
│       │   ├── openalex.py      # OpenAlex API (with circuit breaker)
│       │   ├── semantic_scholar.py
│       │   ├── arxiv.py
│       │   ├── openlibrary.py
│       │   ├── pdf_extract.py   # PDF metadata extraction
│       │   ├── references.py    # Reference extraction from PDFs
│       │   └── zotero_rdf.py    # Zotero RDF import
│       ├── citations/           # citeproc-py CSL formatting
│       └── routes/              # FastAPI endpoints
├── frontend/                    # React + TypeScript + Tailwind
│   └── src/
│       ├── components/          # UI components
│       ├── hooks/               # React hooks
│       └── lib/                 # API client, types
└── README.md
```

## Contributing

Suchi is built on Unix principles: small, composable pieces. Here's where help is most needed:

### High-Impact Issues
- [ ] **Google Drive sync** — storage abstraction layer exists, needs the GDrive backend
- [ ] **Browser extension** — Chrome MV3 extension to save papers from publisher sites (one-click)
- [ ] **Word/Google Docs plugin** — citation insertion while writing
- [ ] **More reference formats** — improve regex parsing for Vancouver, Harvard, numbered styles
- [ ] **Tauri desktop app** — wrap the web UI in a native shell (Rust required)
- [ ] **PDF annotations** — highlight, sticky notes, annotation export

### Good First Issues
- [ ] Add more CSL citation styles (download from [citation-style-language/styles](https://github.com/citation-style-language/styles))
- [ ] Improve title matching in `openalex.py` for short titles
- [ ] Add shell completions for bash/zsh/fish
- [ ] Add `suchi stats` command (total papers, tags, storage used)
- [ ] Add duplicate detection based on DOI/title similarity

### Philosophy
- **CLI first, GUI second** — every feature must work from the terminal
- **Files, not databases** — YAML, JSON, PDF. No SQLite, no binary formats
- **No vendor lock-in** — standard formats, open APIs, your data stays yours
- **Pipe-friendly** — `--json` flag on everything, composable with `jq`, `grep`, `awk`

## Acknowledgements

- **[VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex)** — the PageIndex concept of vectorless, reasoning-based document retrieval. Suchi's `pageindex/` module is inspired by their approach of using LLM reasoning over hierarchical document trees instead of vector embeddings.
- **[Zotero](https://www.zotero.org/)** — the gold standard reference manager. Suchi aims to bring the same quality metadata extraction to a CLI-first, file-based architecture.
- **[CrossRef](https://www.crossref.org/)**, **[OpenAlex](https://openalex.org/)**, **[Semantic Scholar](https://www.semanticscholar.org/)** — the free scholarly APIs that make open research tooling possible.
- **[Tantivy](https://github.com/quickwit-oss/tantivy)** — the Rust search engine powering Suchi's full-text index.
- **[citeproc-py](https://github.com/brechtm/citeproc-py)** — CSL citation formatting.

## License

MIT

---

<p align="center">
  <strong>सूची</strong> — <em>a catalog of knowledge</em>
</p>
