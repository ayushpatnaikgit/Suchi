import { useState, useEffect, useCallback } from "react";
import { useLibrary } from "./hooks/useLibrary";
import { Sidebar } from "./components/layout/Sidebar";
import { Toolbar } from "./components/layout/Toolbar";
import { EntryList } from "./components/library/EntryList";
import { DropZone } from "./components/library/DropZone";
import { ContextMenu } from "./components/library/ContextMenu";
import { MetadataPanel } from "./components/metadata/MetadataPanel";
import { PdfViewer } from "./components/reader/PdfViewer";
import { SettingsPanel } from "./components/settings/SettingsPanel";
import { ChatBubble } from "./components/chat/ChatBubble";
import { api } from "./lib/api";
import { useTheme } from "./hooks/useTheme";
import type { Entry, Collection } from "./lib/types";

/** Collect all ids from a collection tree node and its descendants */
function findCollectionName(tree: Collection[], id: string): string | null {
  for (const node of tree) {
    if (node.id === id) return node.name;
    if (node.children) {
      const found = findCollectionName(node.children, id);
      if (found) return found;
    }
  }
  return null;
}

function collectDescendantIds(tree: Collection[], parentId: string): Set<string> {
  const ids = new Set<string>([parentId]);
  function walk(nodes: Collection[]) {
    for (const node of nodes) {
      if (ids.has(node.id) || ids.has(node.parent_id ?? "")) {
        ids.add(node.id);
      }
      if (node.parent_id && ids.has(node.parent_id)) {
        ids.add(node.id);
      }
      if (node.children) walk(node.children);
    }
  }
  for (let i = 0; i < 5; i++) walk(tree);
  return ids;
}

/** Format a simple APA-style citation */
function formatApaCitation(entry: Entry): string {
  const authors = entry.author
    .map((a) => `${a.family}, ${a.given?.charAt(0) || ""}.`)
    .join(", ");
  const year = entry.date?.split("-")[0] || "n.d.";
  const title = entry.title;
  const journal = entry.journal ? ` *${entry.journal}*` : "";
  const vol = entry.volume ? `, ${entry.volume}` : "";
  const pages = entry.pages ? `, ${entry.pages}` : "";
  const doi = entry.doi ? ` https://doi.org/${entry.doi}` : "";
  return `${authors} (${year}). ${title}.${journal}${vol}${pages}.${doi}`;
}

function App() {
  const { theme, toggleTheme } = useTheme();

  const {
    entries,
    tags,
    collectionTree,
    loading,
    error,
    refresh,
    addByIdentifier,
    deleteEntry,
    uploadPdf,
    createCollection,
    deleteCollection,
    renameCollection,
    addEntryToCollection,
    removeEntryFromCollection,
  } = useLibrary();

  const [selectedEntry, setSelectedEntry] = useState<Entry | null>(null);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filteredEntries, setFilteredEntries] = useState<Entry[]>([]);
  const [viewingPdf, setViewingPdf] = useState<{ url: string; title: string } | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [pdfSelection, setPdfSelection] = useState<{ text: string; entryId: string } | null>(null);
  const [currentPdfPage, setCurrentPdfPage] = useState(1);

  // Sync state
  const [syncStatus, setSyncStatus] = useState<{ logged_in: boolean; email?: string | null; last_sync?: string | null } | null>(null);
  const [syncing, setSyncing] = useState(false);

  // Fetch sync status on mount and periodically
  useEffect(() => {
    const fetchSyncStatus = async () => {
      try {
        const r = await fetch("/api/sync/status");
        if (r.ok) setSyncStatus(await r.json());
      } catch { /* ignore */ }
    };
    fetchSyncStatus();
    const interval = setInterval(fetchSyncStatus, 60000); // Check every minute
    return () => clearInterval(interval);
  }, []);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      const r = await fetch("/api/sync/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await r.json();
      showToast(`Synced: ${data.pushed} pushed, ${data.pulled} pulled`);
      // Refresh sync status
      const status = await fetch("/api/sync/status").then(r => r.json());
      setSyncStatus(status);
      // Refresh entries if anything was pulled
      if (data.pulled > 0) {
        fetchEntries();
        fetchCollections();
      }
    } catch (e) {
      showToast(`Sync failed: ${e instanceof Error ? e.message : "unknown"}`);
    } finally {
      setSyncing(false);
    }
  }, []);

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    entry: Entry;
    x: number;
    y: number;
  } | null>(null);

  // Tag input dialog state
  const [tagDialog, setTagDialog] = useState<{ entryId: string } | null>(null);
  const [tagInput, setTagInput] = useState("");

  // Toast notification
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  }, []);

  // Filter entries based on search, tag, collection
  useEffect(() => {
    let result = entries;

    if (selectedTag) {
      result = result.filter((e) => e.tags.includes(selectedTag));
    }
    if (selectedCollection) {
      const colIds = collectDescendantIds(collectionTree, selectedCollection);
      result = result.filter((e) =>
        e.collections.some((c) => colIds.has(c))
      );
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (e) =>
          e.title.toLowerCase().includes(q) ||
          e.author.some(
            (a) =>
              a.family.toLowerCase().includes(q) ||
              a.given.toLowerCase().includes(q)
          ) ||
          e.tags.some((t) => t.toLowerCase().includes(q)) ||
          (e.abstract && e.abstract.toLowerCase().includes(q)) ||
          (e.doi && e.doi.toLowerCase().includes(q))
      );
    }

    setFilteredEntries(result);
  }, [entries, selectedTag, selectedCollection, searchQuery, collectionTree]);

  // Update selected entry when entries refresh
  useEffect(() => {
    if (selectedEntry) {
      const updated = entries.find((e) => e.id === selectedEntry.id);
      if (updated) setSelectedEntry(updated);
      else setSelectedEntry(null);
    }
  }, [entries]);

  const handleAdd = useCallback(
    async (identifier: string) => {
      const entry = await addByIdentifier(identifier);
      setSelectedEntry(entry);
    },
    [addByIdentifier]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await deleteEntry(id);
      if (selectedEntry?.id === id) {
        setSelectedEntry(null);
        setViewingPdf(null);
      }
    },
    [deleteEntry, selectedEntry]
  );

  const handleExport = useCallback(async () => {
    const bibtex = await api.exportEntries([], "bibtex");
    const blob = new Blob([bibtex], { type: "application/x-bibtex" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "library.bib";
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  const handlePdfDrop = useCallback(
    async (files: File[]) => {
      let lastEntry: Entry | null = null;
      for (const file of files) {
        const entry = await uploadPdf(file);
        lastEntry = entry;
      }
      if (lastEntry) {
        setSelectedEntry(lastEntry);
      }
    },
    [uploadPdf]
  );

  const handleViewPdf = useCallback(async (entry: Entry) => {
    const pdfFile = entry.files.find((f) => f.endsWith(".pdf"));
    if (pdfFile) {
      // Fetch last viewed page to restore position
      let lastPage = 1;
      try {
        const res = await fetch(`/api/entries/${encodeURIComponent(entry.id)}/last-page`);
        if (res.ok) {
          const data = await res.json();
          lastPage = data.page || 1;
        }
      } catch {}

      setViewingPdf({
        url: api.pdfUrl(entry.id, pdfFile),
        title: entry.title,
        initialPage: lastPage,
      });
      setShowSettings(false);
      setPdfSelection(null);
    }
  }, []);

  // ─── Context menu handlers ──────────────────────────────

  const handleContextMenu = useCallback((entry: Entry, x: number, y: number) => {
    setContextMenu({ entry, x, y });
  }, []);

  const handleCopyCitation = useCallback((entry: Entry, _format: string) => {
    const citation = formatApaCitation(entry);
    navigator.clipboard.writeText(citation);
    showToast("Citation copied");
  }, [showToast]);

  const handleCopyDoi = useCallback((doi: string) => {
    navigator.clipboard.writeText(doi);
    showToast("DOI copied");
  }, [showToast]);

  const handleCopyBibtex = useCallback(async (entryId: string) => {
    const bibtex = await api.exportEntries([entryId], "bibtex");
    navigator.clipboard.writeText(bibtex);
    showToast("BibTeX copied");
  }, [showToast]);

  const handleOpenUrl = useCallback((url: string) => {
    window.open(url, "_blank");
  }, []);

  const handleExportEntry = useCallback(async (entryId: string, format: string) => {
    const content = await api.exportEntries([entryId], format);
    const ext = { bibtex: "bib", "csl-json": "json", ris: "ris" }[format] || "txt";
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${entryId}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Exported as ${format}`);
  }, [showToast]);

  const handleAddTag = useCallback((entryId: string) => {
    setTagDialog({ entryId });
    setTagInput("");
  }, []);

  const handleSubmitTag = useCallback(async () => {
    if (!tagDialog || !tagInput.trim()) return;
    const tagsToAdd = tagInput.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
    if (tagsToAdd.length) {
      await api.addTags(tagDialog.entryId, tagsToAdd);
      await refresh();
      showToast(`Added tag${tagsToAdd.length > 1 ? "s" : ""}: ${tagsToAdd.join(", ")}`);
    }
    setTagDialog(null);
    setTagInput("");
  }, [tagDialog, tagInput, refresh, showToast]);

  return (
    <div className="flex h-screen bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100">
      {/* Sidebar */}
      <Sidebar
        tags={tags}
        collectionTree={collectionTree}
        selectedTag={selectedTag}
        selectedCollection={selectedCollection}
        onSelectTag={(t) => {
          setSelectedTag(t);
          setSelectedCollection(null);
        }}
        onSelectCollection={(c) => {
          setSelectedCollection(c);
          setSelectedTag(null);
          // Tell the Zotero Connector which collection is active,
          // so papers saved from the browser go into this collection.
          const colName = c ? findCollectionName(collectionTree, c) : null;
          fetch("http://127.0.0.1:23119/connector/setSelectedCollection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: c, name: colName || "My Library" }),
          }).catch(() => {}); // Silently fail if connector isn't running
        }}
        onRefresh={refresh}
        onCreateCollection={async (name, parentId) => {
          await createCollection(name, parentId);
        }}
        onDeleteCollection={deleteCollection}
        onRenameCollection={renameCollection}
        onDropEntryInCollection={addEntryToCollection}
      />

      {/* Main content */}
      <DropZone onDrop={handlePdfDrop}>
        <div className="flex-1 flex flex-col min-w-0 h-full">
          <Toolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onAdd={handleAdd}
            onExport={handleExport}
            theme={theme}
            onToggleTheme={toggleTheme}
            onOpenSettings={() => setShowSettings(true)}
            syncStatus={syncStatus}
            onSync={handleSync}
            syncing={syncing}
            onImportZotero={() => {
              // Trigger a hidden file input for .rdf files
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".rdf";
              input.onchange = async () => {
                const file = input.files?.[0];
                if (!file) return;
                showToast("Importing Zotero library...");
                try {
                  const formData = new FormData();
                  formData.append("file", file);
                  const res = await fetch("/api/import/zotero-rdf", { method: "POST", body: formData });
                  if (!res.ok) throw new Error(await res.text());
                  const stats = await res.json();
                  showToast(`Imported ${stats.imported} entries, ${stats.collections_created} collections (${stats.skipped} skipped)`);
                  fetchEntries();
                  fetchCollections();
                } catch (err) {
                  showToast(`Import failed: ${err instanceof Error ? err.message : "unknown error"}`);
                }
              };
              input.click();
            }}
            onUploadPdf={() => {
              // Trigger a hidden file input for PDFs
              const input = document.createElement("input");
              input.type = "file";
              input.accept = ".pdf";
              input.onchange = async () => {
                const file = input.files?.[0];
                if (!file) return;
                showToast("Processing PDF...");
                try {
                  const formData = new FormData();
                  formData.append("file", file);
                  const res = await fetch("/api/entries/upload-pdf", { method: "POST", body: formData });
                  if (!res.ok) throw new Error(await res.text());
                  const entry = await res.json();
                  showToast(`Added: ${entry.title}`);
                  fetchEntries();
                } catch (err) {
                  showToast(`Upload failed: ${err instanceof Error ? err.message : "unknown error"}`);
                }
              };
              input.click();
            }}
          />

          <div className="flex-1 flex min-h-0">
            {/* Entry list */}
            <div className="w-[360px] min-w-[280px] border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col">
              {loading ? (
                <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                  Loading...
                </div>
              ) : error ? (
                <div className="flex-1 flex items-center justify-center text-red-400 text-sm p-4">
                  {error}
                </div>
              ) : (
                <EntryList
                  entries={filteredEntries}
                  selectedId={selectedEntry?.id ?? null}
                  onSelect={setSelectedEntry}
                  onContextMenu={handleContextMenu}
                />
              )}
              <div className="px-4 py-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400 dark:text-gray-500">
                {filteredEntries.length} references
              </div>
            </div>

            {/* Reading pane */}
            <div className="flex-1 bg-white dark:bg-gray-900 flex flex-col min-w-0">
              {showSettings ? (
                <SettingsPanel
                  onClose={() => setShowSettings(false)}
                  theme={theme}
                  onToggleTheme={toggleTheme}
                />
              ) : viewingPdf ? (
                <PdfViewer
                  url={viewingPdf.url}
                  title={viewingPdf.title}
                  entryId={selectedEntry?.id || ""}
                  currentCollections={selectedEntry?.collections || []}
                  initialPage={(viewingPdf as any).initialPage || 1}
                  onClose={() => { setViewingPdf(null); setPdfSelection(null); setCurrentPdfPage(1); }}
                  onTextSelected={(text, entryId) => setPdfSelection(text ? { text, entryId } : null)}
                  onNavigateToEntry={(entryId) => {
                    const e = entries.find((x) => x.id === entryId);
                    if (e) { setSelectedEntry(e); setViewingPdf(null); }
                  }}
                  onPageChange={(page) => setCurrentPdfPage(page)}
                />
              ) : selectedEntry ? (
                <MetadataPanel
                  entry={selectedEntry}
                  onDelete={handleDelete}
                  onViewPdf={handleViewPdf}
                  onNavigateToEntry={(entryId) => {
                    const e = entries.find((x) => x.id === entryId);
                    if (e) setSelectedEntry(e);
                  }}
                  onRefresh={refresh}
                />
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-gray-300">
                  <svg
                    className="w-16 h-16 mb-3"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1}
                      d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                    />
                  </svg>
                  <div className="text-sm">
                    Select a reference or drop a PDF here
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </DropZone>

      {/* Right-click context menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          entry={contextMenu.entry}
          collections={collectionTree}
          onClose={() => setContextMenu(null)}
          onAddToCollection={async (colId, entryId) => {
            await addEntryToCollection(colId, entryId);
            showToast("Added to collection");
          }}
          onRemoveFromCollection={async (colId, entryId) => {
            await removeEntryFromCollection(colId, entryId);
            showToast("Removed from collection");
          }}
          onCopyCitation={handleCopyCitation}
          onCopyDoi={handleCopyDoi}
          onCopyBibtex={handleCopyBibtex}
          onOpenPdf={handleViewPdf}
          onOpenUrl={handleOpenUrl}
          onExport={handleExportEntry}
          onDelete={handleDelete}
          onAddTag={handleAddTag}
        />
      )}

      {/* Tag input dialog */}
      {tagDialog && (
        <div className="fixed inset-0 z-[200] bg-black/30 dark:bg-black/50 flex items-center justify-center" onClick={() => setTagDialog(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-80" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-medium mb-2 text-gray-900 dark:text-gray-100">Add Tags</div>
            <input
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubmitTag();
                if (e.key === "Escape") setTagDialog(null);
              }}
              placeholder="tag1, tag2, tag3..."
              className="w-full border border-gray-300 dark:border-gray-600 rounded px-3 py-2 text-sm outline-none focus:border-suchi-light bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setTagDialog(null)}
                className="px-3 py-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">Cancel</button>
              <button onClick={handleSubmitTag}
                className="px-3 py-1.5 text-sm bg-suchi text-white rounded hover:bg-suchi-dark">Add</button>
            </div>
          </div>
        </div>
      )}

      {/* Toast notification */}
      {/* Floating chat bubble */}
      <ChatBubble
        selectedEntry={selectedEntry}
        selectedCollection={selectedCollection}
        collectionTree={collectionTree}
        pdfSelection={pdfSelection}
        viewingPdf={!!viewingPdf}
        entries={entries}
        onNavigateToEntry={(entryId) => {
          const entry = entries.find((e) => e.id === entryId);
          if (entry) {
            setSelectedEntry(entry);
            setViewingPdf(null);
            setShowSettings(false);
          }
        }}
        currentPageNumber={viewingPdf ? currentPdfPage : undefined}
      />

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[300] px-4 py-2 bg-gray-800 text-white rounded-lg shadow-lg text-sm font-medium">
          {toast}
        </div>
      )}
    </div>
  );
}

export default App;
