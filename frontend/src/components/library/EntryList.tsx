import type { Entry } from "../../lib/types";
import { FileText } from "lucide-react";

interface EntryListProps {
  entries: Entry[];
  selectedId: string | null;
  onSelect: (entry: Entry) => void;
  onContextMenu: (entry: Entry, x: number, y: number) => void;
}

function formatAuthors(authors: Entry["author"]): string {
  if (!authors.length) return "Unknown";
  const first = authors[0].family;
  if (authors.length === 1) return first;
  if (authors.length === 2) return `${first} & ${authors[1].family}`;
  return `${first} et al.`;
}

function getYear(date?: string): string {
  if (!date) return "";
  return date.split("-")[0];
}

export function EntryList({ entries, selectedId, onSelect, onContextMenu }: EntryListProps) {
  if (!entries.length) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-600 text-sm">
        No entries found
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {entries.map((entry) => {
        const isSelected = entry.id === selectedId;
        return (
          <button
            key={entry.id}
            onClick={() => onSelect(entry)}
            onContextMenu={(e) => {
              e.preventDefault(); e.stopPropagation();
              onSelect(entry);
              onContextMenu(entry, e.clientX, e.clientY);
            }}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("application/cloudref-entry-id", entry.id);
              e.dataTransfer.effectAllowed = "copy";
            }}
            className={`w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-800 transition-colors cursor-grab active:cursor-grabbing ${
              isSelected
                ? "bg-suchi-50 dark:bg-suchi/20 border-l-2 border-l-suchi"
                : "hover:bg-gray-50 dark:hover:bg-gray-800/50 border-l-2 border-l-transparent"
            }`}
          >
            <div className="flex items-start gap-2">
              <FileText size={14} className={`mt-0.5 flex-shrink-0 ${entry.files.length ? "text-suchi-light dark:text-suchi-light" : "text-gray-300 dark:text-gray-600"}`} />
              <div className="min-w-0">
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100 line-clamp-2 leading-tight">{entry.title}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {formatAuthors(entry.author)}{getYear(entry.date) && ` (${getYear(entry.date)})`}
                </div>
                {entry.journal && <div className="text-xs text-gray-400 dark:text-gray-500 italic truncate">{entry.journal}</div>}
                {entry.tags.length > 0 && (
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {entry.tags.map((tag) => (
                      <span key={tag} className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 rounded">{tag}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
