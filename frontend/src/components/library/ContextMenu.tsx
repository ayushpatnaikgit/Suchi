import { useState, useEffect, useRef } from "react";
import {
  FolderPlus,
  FolderMinus,
  Copy,
  FileText,
  ExternalLink,
  Download,
  Trash2,
  Tag,
  Hash,
  ChevronRight,
  Link,
} from "lucide-react";
import type { Entry, Collection } from "../../lib/types";

export interface ContextMenuAction {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
  submenu?: ContextMenuAction[];
}

interface ContextMenuProps {
  x: number;
  y: number;
  entry: Entry;
  collections: Collection[];
  onClose: () => void;
  onAddToCollection: (collectionId: string, entryId: string) => Promise<void>;
  onRemoveFromCollection: (collectionId: string, entryId: string) => Promise<void>;
  onCopyCitation: (entry: Entry, format: string) => void;
  onCopyDoi: (doi: string) => void;
  onCopyBibtex: (entryId: string) => void;
  onOpenPdf: (entry: Entry) => void;
  onOpenUrl: (url: string) => void;
  onExport: (entryId: string, format: string) => void;
  onDelete: (entryId: string) => void;
  onAddTag: (entryId: string) => void;
}

export function ContextMenu({
  x,
  y,
  entry,
  collections,
  onClose,
  onAddToCollection,
  onRemoveFromCollection,
  onCopyCitation,
  onCopyDoi,
  onCopyBibtex,
  onOpenPdf,
  onOpenUrl,
  onExport,
  onDelete,
  onAddTag,
}: ContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [submenuId, setSubmenuId] = useState<string | null>(null);
  const [adjustedPos, setAdjustedPos] = useState({ x, y });

  // Adjust position to keep menu in viewport
  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const newX = x + rect.width > window.innerWidth ? x - rect.width : x;
      const newY = y + rect.height > window.innerHeight ? y - rect.height : y;
      setAdjustedPos({ x: Math.max(0, newX), y: Math.max(0, newY) });
    }
  }, [x, y]);

  // Close on click outside or Escape
  useEffect(() => {
    const handleClick = () => onClose();
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const hasPdf = entry.files.some((f) => f.endsWith(".pdf"));
  const doi = entry.doi;
  const url = entry.url;

  // Flatten collections for submenu
  const flatCollections = flattenCollections(collections);
  const entryCollections = new Set(entry.collections);

  return (
    <div
      ref={menuRef}
      className="fixed z-[100] bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 min-w-[220px] text-sm"
      style={{ left: adjustedPos.x, top: adjustedPos.y }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Open PDF */}
      {hasPdf && (
        <MenuItem
          icon={<FileText size={14} />}
          label="Open PDF"
          onClick={() => { onOpenPdf(entry); onClose(); }}
        />
      )}

      {/* Open URL */}
      {(doi || url) && (
        <MenuItem
          icon={<ExternalLink size={14} />}
          label={doi ? "Open DOI Link" : "Open URL"}
          onClick={() => {
            onOpenUrl(doi ? `https://doi.org/${doi}` : url!);
            onClose();
          }}
        />
      )}

      <Divider />

      {/* Add to Collection — submenu */}
      <div
        className="relative"
        onMouseEnter={() => setSubmenuId("add-to-collection")}
        onMouseLeave={() => setSubmenuId(null)}
      >
        <MenuItem
          icon={<FolderPlus size={14} />}
          label="Add to Collection"
          hasSubmenu
          onClick={() => {}}
        />
        {submenuId === "add-to-collection" && flatCollections.length > 0 && (
          <Submenu>
            {flatCollections.map((col) => (
              <MenuItem
                key={col.id}
                icon={<span style={{ paddingLeft: col.depth * 12 }} />}
                label={col.name}
                disabled={entryCollections.has(col.id)}
                onClick={async () => {
                  await onAddToCollection(col.id, entry.id);
                  onClose();
                }}
              />
            ))}
            {flatCollections.length === 0 && (
              <div className="px-3 py-2 text-gray-400 italic text-xs">
                No collections
              </div>
            )}
          </Submenu>
        )}
      </div>

      {/* Remove from Collection — submenu (only if entry is in collections) */}
      {entry.collections.length > 0 && (
        <div
          className="relative"
          onMouseEnter={() => setSubmenuId("remove-from-collection")}
          onMouseLeave={() => setSubmenuId(null)}
        >
          <MenuItem
            icon={<FolderMinus size={14} />}
            label="Remove from Collection"
            hasSubmenu
            onClick={() => {}}
          />
          {submenuId === "remove-from-collection" && (
            <Submenu>
              {entry.collections.map((colId) => {
                const col = flatCollections.find((c) => c.id === colId);
                return (
                  <MenuItem
                    key={colId}
                    label={col?.name || colId}
                    icon={<FolderMinus size={12} />}
                    onClick={async () => {
                      await onRemoveFromCollection(colId, entry.id);
                      onClose();
                    }}
                  />
                );
              })}
            </Submenu>
          )}
        </div>
      )}

      {/* Add Tag */}
      <MenuItem
        icon={<Tag size={14} />}
        label="Add Tag..."
        onClick={() => { onAddTag(entry.id); onClose(); }}
      />

      <Divider />

      {/* Copy actions */}
      <MenuItem
        icon={<Copy size={14} />}
        label="Copy Citation (APA)"
        onClick={() => { onCopyCitation(entry, "apa"); onClose(); }}
      />

      <MenuItem
        icon={<Copy size={14} />}
        label="Copy BibTeX"
        onClick={() => { onCopyBibtex(entry.id); onClose(); }}
      />

      {doi && (
        <MenuItem
          icon={<Hash size={14} />}
          label="Copy DOI"
          onClick={() => { onCopyDoi(doi); onClose(); }}
        />
      )}

      <MenuItem
        icon={<Link size={14} />}
        label="Copy Link"
        onClick={() => {
          const link = doi ? `https://doi.org/${doi}` : url || "";
          if (link) navigator.clipboard.writeText(link);
          onClose();
        }}
        disabled={!doi && !url}
      />

      <Divider />

      {/* Export */}
      <div
        className="relative"
        onMouseEnter={() => setSubmenuId("export")}
        onMouseLeave={() => setSubmenuId(null)}
      >
        <MenuItem
          icon={<Download size={14} />}
          label="Export As..."
          hasSubmenu
          onClick={() => {}}
        />
        {submenuId === "export" && (
          <Submenu>
            <MenuItem label="BibTeX" onClick={() => { onExport(entry.id, "bibtex"); onClose(); }} />
            <MenuItem label="CSL-JSON" onClick={() => { onExport(entry.id, "csl-json"); onClose(); }} />
            <MenuItem label="RIS" onClick={() => { onExport(entry.id, "ris"); onClose(); }} />
          </Submenu>
        )}
      </div>

      <Divider />

      {/* Delete */}
      <MenuItem
        icon={<Trash2 size={14} />}
        label="Move to Trash"
        danger
        onClick={() => {
          if (confirm(`Delete "${entry.title}"?`)) {
            onDelete(entry.id);
          }
          onClose();
        }}
      />
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────

function MenuItem({
  icon,
  label,
  onClick,
  danger,
  disabled,
  hasSubmenu,
}: {
  icon?: React.ReactNode;
  label: string;
  onClick?: () => void;
  danger?: boolean;
  disabled?: boolean;
  hasSubmenu?: boolean;
}) {
  return (
    <button
      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 transition-colors ${
        disabled
          ? "text-gray-300 dark:text-gray-600 cursor-default"
          : danger
          ? "text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
          : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
      }`}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
    >
      {icon && <span className="w-4 flex-shrink-0 flex items-center">{icon}</span>}
      <span className="flex-1 truncate">{label}</span>
      {hasSubmenu && <ChevronRight size={12} className="text-gray-400" />}
    </button>
  );
}

function Divider() {
  return <div className="my-1 border-t border-gray-100 dark:border-gray-700" />;
}

function Submenu({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute left-full top-0 ml-0.5 bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700 py-1 min-w-[180px] max-h-[300px] overflow-y-auto">
      {children}
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────

interface FlatCollection {
  id: string;
  name: string;
  depth: number;
}

function flattenCollections(tree: Collection[], depth = 0): FlatCollection[] {
  const result: FlatCollection[] = [];
  for (const col of tree) {
    result.push({ id: col.id, name: col.name, depth });
    if (col.children?.length) {
      result.push(...flattenCollections(col.children, depth + 1));
    }
  }
  return result;
}
