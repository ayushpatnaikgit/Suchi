import { useState } from "react";
import {
  BookOpen,
  Tag,
  FolderOpen,
  FolderClosed,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Plus,
  Trash2,
} from "lucide-react";
import type { Collection } from "../../lib/types";

interface SidebarProps {
  tags: string[];
  collectionTree: Collection[];
  selectedTag: string | null;
  selectedCollection: string | null;
  onSelectTag: (tag: string | null) => void;
  onSelectCollection: (col: string | null) => void;
  onRefresh: () => void;
  onCreateCollection: (name: string, parentId?: string | null) => Promise<void>;
  onDeleteCollection: (id: string) => Promise<void>;
  onRenameCollection: (id: string, name: string) => Promise<void>;
  onDropEntryInCollection: (collectionId: string, entryId: string) => Promise<void>;
}

export function Sidebar({
  tags,
  collectionTree,
  selectedTag,
  selectedCollection,
  onSelectTag,
  onSelectCollection,
  onRefresh,
  onCreateCollection,
  onDeleteCollection,
  onRenameCollection,
  onDropEntryInCollection,
}: SidebarProps) {
  const [showNewCollection, setShowNewCollection] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionParent, setNewCollectionParent] = useState<string | null>(null);

  const handleCreateCollection = async () => {
    if (!newCollectionName.trim()) return;
    await onCreateCollection(newCollectionName.trim(), newCollectionParent);
    setNewCollectionName("");
    setShowNewCollection(false);
    setNewCollectionParent(null);
  };

  return (
    <div className="w-[220px] min-w-[220px] bg-gray-50 dark:bg-gray-950 border-r border-gray-200 dark:border-gray-800 flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <img src="/favicon.png" alt="Suchi" className="w-5 h-5 rounded" />
          <span className="font-semibold text-sm text-gray-900 dark:text-gray-100">Suchi</span>
        </div>
        <button
          onClick={onRefresh}
          className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"
          title="Refresh"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {/* All items */}
        <button
          onClick={() => { onSelectTag(null); onSelectCollection(null); }}
          className={`w-full text-left px-2 py-1.5 rounded text-sm flex items-center gap-2 ${
            !selectedTag && !selectedCollection
              ? "bg-suchi-50 dark:bg-suchi/20 text-suchi-700 dark:text-suchi-light"
              : "hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300"
          }`}
        >
          <BookOpen size={14} />
          All References
        </button>

        {/* Collections */}
        <div>
          <div className="flex items-center justify-between mb-1 px-2">
            <span className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">Collections</span>
            <button
              onClick={() => { setNewCollectionParent(null); setShowNewCollection(true); }}
              className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              title="New collection"
            >
              <Plus size={12} />
            </button>
          </div>

          {showNewCollection && newCollectionParent === null && (
            <div className="px-2 mb-1">
              <input
                type="text"
                value={newCollectionName}
                onChange={(e) => setNewCollectionName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateCollection();
                  if (e.key === "Escape") { setShowNewCollection(false); setNewCollectionName(""); }
                }}
                placeholder="Collection name..."
                className="w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs outline-none focus:border-suchi-light bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
                autoFocus
              />
            </div>
          )}

          {collectionTree.length > 0 ? (
            collectionTree.map((col) => (
              <CollectionNode
                key={col.id}
                collection={col}
                depth={0}
                selectedCollection={selectedCollection}
                onSelect={onSelectCollection}
                onCreateChild={(parentId) => { setNewCollectionParent(parentId); setShowNewCollection(true); }}
                onDelete={onDeleteCollection}
                onRename={onRenameCollection}
                onDropEntry={onDropEntryInCollection}
                showNewInput={showNewCollection}
                newParentId={newCollectionParent}
                newName={newCollectionName}
                onNewNameChange={setNewCollectionName}
                onNewSubmit={handleCreateCollection}
                onNewCancel={() => { setShowNewCollection(false); setNewCollectionName(""); setNewCollectionParent(null); }}
              />
            ))
          ) : !showNewCollection ? (
            <div className="px-2 text-xs text-gray-400 dark:text-gray-600 italic">No collections yet</div>
          ) : null}
        </div>

        {/* Tags */}
        {tags.length > 0 && (
          <div>
            <div className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1 px-2">Tags</div>
            {tags.map((tag) => (
              <button
                key={tag}
                onClick={() => onSelectTag(selectedTag === tag ? null : tag)}
                className={`w-full text-left px-2 py-1 rounded text-sm flex items-center gap-2 ${
                  selectedTag === tag
                    ? "bg-suchi-50 dark:bg-suchi/20 text-suchi-700 dark:text-suchi-light"
                    : "hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
                }`}
              >
                <Tag size={12} />
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Recursive tree node ────

interface CollectionNodeProps {
  collection: Collection;
  depth: number;
  selectedCollection: string | null;
  onSelect: (id: string | null) => void;
  onCreateChild: (parentId: string) => void;
  onDelete: (id: string) => Promise<void>;
  onRename: (id: string, name: string) => Promise<void>;
  onDropEntry: (collectionId: string, entryId: string) => Promise<void>;
  showNewInput: boolean;
  newParentId: string | null;
  newName: string;
  onNewNameChange: (name: string) => void;
  onNewSubmit: () => void;
  onNewCancel: () => void;
}

function CollectionNode({
  collection, depth, selectedCollection, onSelect, onCreateChild, onDelete, onRename, onDropEntry,
  showNewInput, newParentId, newName, onNewNameChange, onNewSubmit, onNewCancel,
}: CollectionNodeProps) {
  const [expanded, setExpanded] = useState(true);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(collection.name);
  const [isDragOver, setIsDragOver] = useState(false);
  const hasChildren = collection.children && collection.children.length > 0;
  const isSelected = selectedCollection === collection.id;

  const handleRename = async () => {
    if (renameValue.trim() && renameValue !== collection.name) await onRename(collection.id, renameValue.trim());
    setIsRenaming(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes("application/cloudref-entry-id")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setIsDragOver(true); }
  };
  const handleDragLeave = () => setIsDragOver(false);
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault(); setIsDragOver(false);
    const entryId = e.dataTransfer.getData("application/cloudref-entry-id");
    if (entryId) await onDropEntry(collection.id, entryId);
  };

  return (
    <div>
      <div
        onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}
        className={`group flex items-center gap-1 rounded text-sm cursor-pointer transition-colors ${
          isDragOver
            ? "bg-suchi-100 dark:bg-suchi/30 text-suchi-700 dark:text-suchi-light ring-1 ring-suchi"
            : isSelected
            ? "bg-suchi-50 dark:bg-suchi/20 text-suchi-700 dark:text-suchi-light"
            : "hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
        }`}
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        <button onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }} className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 flex-shrink-0">
          {hasChildren ? (expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="w-3" />}
        </button>
        {expanded && hasChildren
          ? <FolderOpen size={14} className="flex-shrink-0 text-yellow-600 dark:text-yellow-400" />
          : <FolderClosed size={14} className="flex-shrink-0 text-yellow-600 dark:text-yellow-400" />}
        {isRenaming ? (
          <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleRename(); if (e.key === "Escape") setIsRenaming(false); }}
            onBlur={handleRename}
            className="flex-1 border border-gray-300 dark:border-gray-600 rounded px-1 py-0.5 text-xs outline-none bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100" autoFocus />
        ) : (
          <span className="flex-1 py-1 truncate text-sm" onClick={() => onSelect(isSelected ? null : collection.id)}
            onDoubleClick={() => { setRenameValue(collection.name); setIsRenaming(true); }}>{collection.name}</span>
        )}
        <div className="hidden group-hover:flex items-center gap-0.5 pr-1">
          <button onClick={(e) => { e.stopPropagation(); onCreateChild(collection.id); }}
            className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400" title="New subcollection"><Plus size={10} /></button>
          <button onClick={async (e) => { e.stopPropagation(); if (confirm(`Delete "${collection.name}"?`)) await onDelete(collection.id); }}
            className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500" title="Delete"><Trash2 size={10} /></button>
        </div>
      </div>

      {expanded && hasChildren && (
        <div>
          {collection.children.map((child) => (
            <CollectionNode key={child.id} collection={child} depth={depth + 1} selectedCollection={selectedCollection}
              onSelect={onSelect} onCreateChild={onCreateChild} onDelete={onDelete} onRename={onRename} onDropEntry={onDropEntry}
              showNewInput={showNewInput} newParentId={newParentId} newName={newName}
              onNewNameChange={onNewNameChange} onNewSubmit={onNewSubmit} onNewCancel={onNewCancel} />
          ))}
        </div>
      )}

      {showNewInput && newParentId === collection.id && expanded && (
        <div style={{ paddingLeft: `${24 + depth * 16}px` }} className="py-1">
          <input type="text" value={newName} onChange={(e) => onNewNameChange(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onNewSubmit(); if (e.key === "Escape") onNewCancel(); }}
            placeholder="Subcollection name..."
            className="w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs outline-none focus:border-suchi-light bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100" autoFocus />
        </div>
      )}
    </div>
  );
}
