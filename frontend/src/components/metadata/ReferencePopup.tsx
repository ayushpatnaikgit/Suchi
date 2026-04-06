import { useState } from "react";
import { X, Plus, ExternalLink, Check, BookOpen, Loader2, Quote, FileText } from "lucide-react";

interface Reference {
  raw_text: string;
  title?: string;
  authors_raw?: string;
  year?: string;
  doi?: string;
  url?: string;
  abstract?: string;
  journal?: string;
  cited_by_count?: number;
  tags?: string[];
  pdf_url?: string;
  resolved?: boolean;
  in_library: boolean;
  library_id?: string;
}

interface ReferencePopupProps {
  reference: Reference;
  currentCollections: string[];  // Collections of the paper being viewed
  position: { x: number; y: number };
  onClose: () => void;
  onAddToLibrary: (doi: string | null, title: string | null, collections: string[]) => Promise<void>;
  onNavigateToEntry: (entryId: string) => void;
}

export function ReferencePopup({
  reference,
  currentCollections,
  position,
  onClose,
  onAddToLibrary,
  onNavigateToEntry,
}: ReferencePopupProps) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);

  const handleAdd = async () => {
    setAdding(true);
    try {
      await onAddToLibrary(
        reference.doi || null,
        reference.title || null,
        currentCollections
      );
      setAdded(true);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setAdding(false);
    }
  };

  // Clamp position to viewport
  const POPUP_WIDTH = 480;
  const POPUP_MAX_HEIGHT = Math.min(600, window.innerHeight - 32);
  const left = Math.min(position.x, window.innerWidth - POPUP_WIDTH - 8);
  const top = Math.min(position.y, window.innerHeight - POPUP_MAX_HEIGHT - 8);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-[150]" onClick={onClose} />

      {/* Popup */}
      <div
        className="fixed z-[160] bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col"
        style={{
          left: Math.max(8, left),
          top: Math.max(8, top),
          width: POPUP_WIDTH,
          maxHeight: POPUP_MAX_HEIGHT,
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 dark:border-gray-700 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">Reference</span>
            {reference.resolved && (
              <span className="text-[10px] px-1.5 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300 rounded font-medium">
                Resolved via OpenAlex
              </span>
            )}
          </div>
          <button onClick={onClose} className="p-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400">
            <X size={14} />
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-y-auto flex-1">
          {/* Title */}
          {reference.title ? (
            <div className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug">
              {reference.title}
            </div>
          ) : (
            <div className="text-sm text-gray-600 dark:text-gray-300 italic leading-snug">
              {reference.raw_text.slice(0, 150)}...
            </div>
          )}

          {/* Authors + Year + Journal */}
          <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
            {reference.authors_raw && (
              <div>{reference.authors_raw.slice(0, 200)}</div>
            )}
            <div className="flex items-center gap-3 flex-wrap">
              {reference.year && <span>{reference.year}</span>}
              {reference.journal && (
                <span className="italic">{reference.journal}</span>
              )}
              {typeof reference.cited_by_count === "number" && reference.cited_by_count > 0 && (
                <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                  <Quote size={10} />
                  {reference.cited_by_count.toLocaleString()} citations
                </span>
              )}
            </div>
            {reference.doi && (
              <div className="font-mono text-[10px] text-gray-400 dark:text-gray-500 pt-1 break-all">
                {reference.doi}
              </div>
            )}
          </div>

          {/* Abstract */}
          {reference.resolved && (
            <div className="space-y-1">
              <div className="flex items-center gap-1 text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                <FileText size={10} />
                Abstract
              </div>
              {reference.abstract ? (
                <div className="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
                  {reference.abstract}
                </div>
              ) : (
                <div className="text-xs text-gray-400 dark:text-gray-500 italic">
                  Abstract not available in OpenAlex or Semantic Scholar for this paper.
                </div>
              )}
            </div>
          )}

          {/* Tags */}
          {reference.tags && reference.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {reference.tags.slice(0, 6).map((tag) => (
                <span
                  key={tag}
                  className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

        </div>

        {/* Footer: Actions (always visible) */}
        <div className="flex-shrink-0 border-t border-gray-100 dark:border-gray-700 p-3 space-y-2">
          <div className="flex gap-2 flex-wrap">
            {reference.in_library && reference.library_id ? (
              <button
                onClick={() => {
                  onNavigateToEntry(reference.library_id!);
                  onClose();
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800 rounded text-xs font-medium hover:bg-green-100 dark:hover:bg-green-900/50"
              >
                <BookOpen size={12} />
                In Library — View
              </button>
            ) : added ? (
              <span className="flex items-center gap-1.5 px-3 py-1.5 text-green-600 dark:text-green-400 text-xs font-medium">
                <Check size={12} />
                Added to library
              </span>
            ) : (
              <button
                onClick={handleAdd}
                disabled={adding || (!reference.doi && !reference.title)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {adding ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                {adding ? "Adding..." : "Add to Library"}
              </button>
            )}

            {reference.doi && (
              <a
                href={`https://doi.org/${reference.doi}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ExternalLink size={12} />
                DOI
              </a>
            )}

            {reference.url && (
              <a
                href={reference.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 dark:border-gray-600 rounded text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                <ExternalLink size={12} />
                Link
              </a>
            )}
          </div>

          {/* Note about auto-collection */}
          {!reference.in_library && !added && currentCollections.length > 0 && (
            <div className="text-[10px] text-gray-400 dark:text-gray-500 italic">
              Will be added to the same collection{currentCollections.length > 1 ? "s" : ""} as the current paper
            </div>
          )}
        </div>
      </div>
    </>
  );
}
