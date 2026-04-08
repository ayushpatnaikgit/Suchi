import { useState, useRef, useEffect } from "react";
import { Plus, Search, Download, Sun, Moon, Settings, ChevronDown, FileText, Upload, Library, Cloud, CloudOff, RefreshCw, Loader2 } from "lucide-react";
import type { Theme } from "../../hooks/useTheme";

interface ToolbarProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onAdd: (identifier: string) => Promise<void>;
  onExport: () => void;
  theme: Theme;
  onToggleTheme: () => void;
  onOpenSettings: () => void;
  onImportZotero?: () => void;
  onUploadPdf?: () => void;
  syncStatus?: { logged_in: boolean; email?: string | null; last_sync?: string | null } | null;
  onSync?: () => void;
  syncing?: boolean;
}

export function Toolbar({ searchQuery, onSearchChange, onAdd, onExport, theme, onToggleTheme, onOpenSettings, onImportZotero, onUploadPdf, syncStatus, onSync, syncing }: ToolbarProps) {
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [showAddInput, setShowAddInput] = useState(false);
  const [addInput, setAddInput] = useState("");
  const [adding, setAdding] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowAddMenu(false);
      }
    };
    if (showAddMenu) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showAddMenu]);

  const handleAdd = async () => {
    if (!addInput.trim()) return;
    setAdding(true);
    try {
      await onAdd(addInput.trim());
      setAddInput("");
      setShowAddInput(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to add entry");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="h-12 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex items-center px-3 gap-2">
      {/* Search */}
      <div className="flex-1 flex items-center gap-2 bg-gray-100 dark:bg-gray-800 rounded-lg px-3 py-1.5">
        <Search size={14} className="text-gray-400 dark:text-gray-500" />
        <input
          type="text"
          placeholder="Search references..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="bg-transparent outline-none text-sm flex-1 text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500"
        />
      </div>

      {/* Add — input mode */}
      {showAddInput ? (
        <div className="flex items-center gap-1">
          <input
            type="text"
            placeholder="DOI, ISBN, arXiv ID..."
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            className="border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-sm w-56 outline-none focus:border-suchi-light bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
            autoFocus
            disabled={adding}
          />
          <button onClick={handleAdd} disabled={adding}
            className="px-2 py-1 bg-suchi text-white rounded text-sm hover:bg-suchi-dark disabled:opacity-50">
            {adding ? "..." : "Add"}
          </button>
          <button onClick={() => setShowAddInput(false)}
            className="px-2 py-1 text-gray-500 dark:text-gray-400 text-sm hover:text-gray-700 dark:hover:text-gray-200">
            Cancel
          </button>
        </div>
      ) : (
        /* Add — dropdown button */
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowAddMenu(!showAddMenu)}
            className="flex items-center gap-1 px-3 py-1.5 bg-suchi text-white rounded-lg text-sm hover:bg-suchi-dark"
          >
            <Plus size={14} />
            Add
            <ChevronDown size={12} className={`transition-transform ${showAddMenu ? "rotate-180" : ""}`} />
          </button>

          {showAddMenu && (
            <div className="absolute right-0 top-full mt-1 w-56 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl z-50 py-1">
              <button
                onClick={() => { setShowAddMenu(false); setShowAddInput(true); }}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <FileText size={15} className="text-suchi-light" />
                <div className="text-left">
                  <div className="font-medium">Add by identifier</div>
                  <div className="text-xs text-gray-400 dark:text-gray-500">DOI, ISBN, arXiv ID, URL</div>
                </div>
              </button>

              <button
                onClick={() => { setShowAddMenu(false); onUploadPdf?.(); }}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <Upload size={15} className="text-green-500" />
                <div className="text-left">
                  <div className="font-medium">Upload PDF</div>
                  <div className="text-xs text-gray-400 dark:text-gray-500">Drag & drop or select a PDF file</div>
                </div>
              </button>

              <div className="border-t border-gray-200 dark:border-gray-700 my-1" />

              <button
                onClick={() => { setShowAddMenu(false); onImportZotero?.(); }}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <Library size={15} className="text-red-500" />
                <div className="text-left">
                  <div className="font-medium">Import from Zotero</div>
                  <div className="text-xs text-gray-400 dark:text-gray-500">Upload .rdf export file</div>
                </div>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Export */}
      <button
        onClick={onExport}
        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
        title="Export BibTeX"
      >
        <Download size={16} />
      </button>

      {/* Sync indicator */}
      {syncStatus?.logged_in ? (
        <button
          onClick={onSync}
          disabled={syncing}
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-green-500 dark:text-green-400 relative"
          title={syncing ? "Syncing..." : `Synced as ${syncStatus.email || "unknown"}${syncStatus.last_sync ? `\nLast sync: ${new Date(syncStatus.last_sync).toLocaleString()}` : ""}\nClick to sync now`}
        >
          {syncing ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Cloud size={16} />
          )}
          {/* Green dot indicator */}
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-500 rounded-full" />
        </button>
      ) : (
        <button
          onClick={onOpenSettings}
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 dark:text-gray-600"
          title="Not connected — click to set up sync"
        >
          <CloudOff size={16} />
        </button>
      )}

      {/* Theme toggle */}
      <button
        onClick={onToggleTheme}
        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
        title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      >
        {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
      </button>

      {/* Settings */}
      <button
        onClick={onOpenSettings}
        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
        title="Settings"
      >
        <Settings size={16} />
      </button>
    </div>
  );
}
