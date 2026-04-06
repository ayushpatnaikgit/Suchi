import { useState, useEffect, useCallback } from "react";
import type { Entry, Collection } from "../lib/types";
import { api } from "../lib/api";

export function useLibrary() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [collectionTree, setCollectionTree] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [e, t, ct] = await Promise.all([
        api.listEntries({ limit: 500 }),
        api.getTags(),
        api.getCollectionTree(),
      ]);
      setEntries(e);
      setTags(t);
      setCollectionTree(ct);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const addByIdentifier = useCallback(
    async (identifier: string, entryTags: string[] = []) => {
      const entry = await api.addByIdentifier(identifier, entryTags);
      await refresh();
      return entry;
    },
    [refresh]
  );

  const deleteEntry = useCallback(
    async (id: string) => {
      await api.deleteEntry(id);
      await refresh();
    },
    [refresh]
  );

  const uploadPdf = useCallback(
    async (file: File) => {
      const entry = await api.uploadPdf(file);
      await refresh();
      return entry;
    },
    [refresh]
  );

  const createCollection = useCallback(
    async (name: string, parentId?: string | null) => {
      const col = await api.createCollection(name, parentId);
      await refresh();
      return col;
    },
    [refresh]
  );

  const deleteCollection = useCallback(
    async (id: string) => {
      await api.deleteCollection(id, false);
      await refresh();
    },
    [refresh]
  );

  const renameCollection = useCallback(
    async (id: string, name: string) => {
      await api.renameCollection(id, name);
      await refresh();
    },
    [refresh]
  );

  const addEntryToCollection = useCallback(
    async (collectionId: string, entryId: string) => {
      await api.addEntryToCollection(collectionId, entryId);
      await refresh();
    },
    [refresh]
  );

  const removeEntryFromCollection = useCallback(
    async (collectionId: string, entryId: string) => {
      await api.removeEntryFromCollection(collectionId, entryId);
      await refresh();
    },
    [refresh]
  );

  const search = useCallback(async (query: string) => {
    if (!query.trim()) {
      return api.listEntries({ limit: 500 });
    }
    return api.search(query);
  }, []);

  return {
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
    search,
  };
}
