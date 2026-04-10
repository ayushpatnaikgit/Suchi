import type { Entry, Collection } from "./types";

// Absolute URL to the local Python backend. Using an absolute URL works both
// in dev (Vite's proxy is bypassed — backend has CORS open) and in the bundled
// Tauri app (where there's no dev proxy and relative /api paths would resolve
// to the Tauri protocol origin).
export const API_HOST = "http://127.0.0.1:9876";
const BASE = `${API_HOST}/api`;

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  // Entries
  listEntries(params?: { tag?: string; collection?: string; limit?: number }) {
    const q = new URLSearchParams();
    if (params?.tag) q.set("tag", params.tag);
    if (params?.collection) q.set("collection", params.collection);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return fetchJSON<Entry[]>(`/entries${qs ? `?${qs}` : ""}`);
  },

  getEntry(id: string) {
    return fetchJSON<Entry>(`/entries/${encodeURIComponent(id)}`);
  },

  addByIdentifier(identifier: string, tags: string[] = [], collections: string[] = []) {
    return fetchJSON<Entry>("/entries/resolve", {
      method: "POST",
      body: JSON.stringify({ identifier, tags, collections }),
    });
  },

  createEntry(data: Partial<Entry>) {
    return fetchJSON<Entry>("/entries", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  updateEntry(id: string, updates: Partial<Entry>) {
    return fetchJSON<Entry>(`/entries/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(updates),
    });
  },

  deleteEntry(id: string) {
    return fetchJSON<{ ok: boolean }>(`/entries/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  addTags(id: string, tags: string[]) {
    return fetchJSON<Entry>(`/entries/${encodeURIComponent(id)}/tags`, {
      method: "POST",
      body: JSON.stringify(tags),
    });
  },

  // Search (Tantivy + RapidFuzz)
  search(
    q: string,
    filters?: { year?: string; author?: string; tag?: string; collection?: string; journal?: string },
    limit = 50
  ) {
    const params = new URLSearchParams();
    params.set("q", q);
    params.set("limit", String(limit));
    if (filters?.year) params.set("year", filters.year);
    if (filters?.author) params.set("author", filters.author);
    if (filters?.tag) params.set("tag", filters.tag);
    if (filters?.collection) params.set("collection", filters.collection);
    if (filters?.journal) params.set("journal", filters.journal);
    return fetchJSON<Entry[]>(`/search?${params}`);
  },

  getTags() {
    return fetchJSON<string[]>("/search/tags");
  },

  getCollections() {
    return fetchJSON<string[]>("/search/collections");
  },

  // Export
  exportEntries(entryIds: string[] = [], format = "bibtex") {
    return fetch(`${BASE}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_ids: entryIds, format }),
    }).then((r) => r.text());
  },

  // Upload PDF (drag-and-drop)
  async uploadPdf(file: File): Promise<Entry> {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE}/entries/upload-pdf`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Upload failed: ${text}`);
    }
    return res.json();
  },

  // PDF URL
  pdfUrl(entryId: string, filename = "document.pdf") {
    return `${BASE}/entries/${encodeURIComponent(entryId)}/pdf?filename=${encodeURIComponent(filename)}`;
  },

  // Collections
  getCollectionTree() {
    return fetchJSON<Collection[]>("/collections/tree");
  },

  getCollectionsFlat() {
    return fetchJSON<Collection[]>("/collections/flat");
  },

  createCollection(name: string, parentId?: string | null, color?: string) {
    return fetchJSON<Collection>("/collections/create", {
      method: "POST",
      body: JSON.stringify({ name, parent_id: parentId ?? null, color }),
    });
  },

  renameCollection(id: string, name: string) {
    return fetchJSON<Collection>("/collections/update", {
      method: "PUT",
      body: JSON.stringify({ id, name }),
    });
  },

  moveCollection(id: string, parentId: string | null) {
    return fetchJSON<Collection>("/collections/update", {
      method: "PUT",
      body: JSON.stringify({ id, parent_id: parentId }),
    });
  },

  deleteCollection(id: string, deleteChildren = false) {
    return fetchJSON<{ ok: boolean }>(
      `/collections/delete?id=${encodeURIComponent(id)}&delete_children=${deleteChildren}`,
      { method: "DELETE" }
    );
  },

  addEntryToCollection(collectionId: string, entryId: string) {
    return fetchJSON<{ ok: boolean }>("/collections/add-entry", {
      method: "POST",
      body: JSON.stringify({ collection_id: collectionId, entry_id: entryId }),
    });
  },

  removeEntryFromCollection(collectionId: string, entryId: string) {
    return fetchJSON<{ ok: boolean }>("/collections/remove-entry", {
      method: "POST",
      body: JSON.stringify({ collection_id: collectionId, entry_id: entryId }),
    });
  },
};
