import { useState, useEffect } from "react";
import { Sparkles, X, FileText, FolderOpen, MessageSquareQuote, BookOpen } from "lucide-react";
import { ChatPanel, type ChatContext } from "./ChatPanel";
import type { Entry, Collection } from "../../lib/types";

interface ChatBubbleProps {
  selectedEntry: Entry | null;
  selectedCollection: string | null;
  collectionTree: Collection[];
  pdfSelection: { text: string; entryId: string } | null;
  viewingPdf: boolean;
  entries: Entry[];
  onNavigateToEntry: (entryId: string) => void;
  currentPageNumber?: number;
}

function findCollectionName(tree: Collection[], id: string): string {
  for (const col of tree) {
    if (col.id === id) return col.name;
    if (col.children) {
      const found = findCollectionName(col.children, id);
      if (found) return found;
    }
  }
  return id;
}

export function ChatBubble({
  selectedEntry,
  selectedCollection,
  collectionTree,
  pdfSelection,
  viewingPdf,
  entries,
  onNavigateToEntry,
  currentPageNumber,
}: ChatBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [chatContext, setChatContext] = useState<ChatContext | null>(null);
  const [showContextPicker, setShowContextPicker] = useState(false);

  // Auto-update context when selection changes while chat is open
  useEffect(() => {
    if (isOpen && chatContext?.type === "selection" && pdfSelection?.text) {
      setChatContext({
        type: "selection",
        selectedText: pdfSelection.text,
        entryIdForSelection: pdfSelection.entryId,
        label: "Selected text",
      });
    }
  }, [pdfSelection]);

  const getAvailableContexts = () => {
    const contexts: { label: string; description: string; icon: React.ReactNode; context: ChatContext; priority: number }[] = [];

    if (pdfSelection?.text && viewingPdf) {
      contexts.push({
        label: "Selected text",
        description: `"${pdfSelection.text.slice(0, 50)}${pdfSelection.text.length > 50 ? "..." : ""}"`,
        icon: <MessageSquareQuote size={16} className="text-yellow-500" />,
        priority: 1,
        context: { type: "selection", selectedText: pdfSelection.text, entryIdForSelection: pdfSelection.entryId, label: "Selected text" },
      });
    }

    if (selectedEntry) {
      contexts.push({
        label: "This paper",
        description: selectedEntry.title.slice(0, 60),
        icon: <FileText size={16} className="text-blue-500" />,
        priority: 2,
        context: { type: "paper", entryId: selectedEntry.id, label: selectedEntry.title.slice(0, 40) },
      });
    }

    if (selectedCollection) {
      const name = findCollectionName(collectionTree, selectedCollection);
      contexts.push({
        label: "This collection",
        description: name,
        icon: <FolderOpen size={16} className="text-yellow-600" />,
        priority: 3,
        context: { type: "collection", collectionId: selectedCollection, label: name },
      });
    }

    contexts.push({
      label: "General",
      description: "Ask anything about research",
      icon: <BookOpen size={16} className="text-gray-400" />,
      priority: 10,
      context: { type: "general", label: "General" },
    });

    return contexts.sort((a, b) => a.priority - b.priority);
  };

  const handleOpen = () => {
    if (isOpen) {
      setIsOpen(false);
      setChatContext(null);
      setShowContextPicker(false);
      return;
    }

    const contexts = getAvailableContexts();
    const nonGeneral = contexts.filter((c) => c.context.type !== "general");

    if (nonGeneral.length === 0) {
      // No specific context — open general chat directly
      setChatContext(contexts[0].context);
      setShowContextPicker(false);
    } else if (nonGeneral.length === 1) {
      // One specific context — use it directly, no picker needed
      setChatContext(nonGeneral[0].context);
      setShowContextPicker(false);
    } else {
      // Multiple specific contexts — show picker
      setShowContextPicker(true);
      setChatContext(null);
    }
    setIsOpen(true);
  };

  return (
    <>
      {/* Slide-out chat panel */}
      {isOpen && (
        <div className="fixed bottom-20 right-6 z-[80] w-[420px] h-[560px] rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden bg-white dark:bg-gray-900 flex flex-col">
          {showContextPicker && !chatContext ? (
            <div className="flex flex-col h-full">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2">
                  <Sparkles size={16} className="text-purple-500" />
                  <span className="font-medium text-sm text-gray-900 dark:text-gray-100">Chat about...</span>
                </div>
                <button onClick={() => { setIsOpen(false); setShowContextPicker(false); }}
                  className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400"><X size={16} /></button>
              </div>
              <div className="flex-1 p-4 space-y-2">
                {getAvailableContexts().map((opt, i) => (
                  <button key={i}
                    onClick={() => { setChatContext(opt.context); setShowContextPicker(false); }}
                    className="w-full flex items-center gap-3 px-4 py-3 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 border border-gray-200 dark:border-gray-700 transition-colors text-left">
                    <div className="w-9 h-9 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0">{opt.icon}</div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{opt.label}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{opt.description}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : chatContext ? (
            <ChatPanel
              context={chatContext}
              onClose={() => { setChatContext(null); setIsOpen(false); setShowContextPicker(false); }}
              onChangeContext={() => { setChatContext(null); setShowContextPicker(true); }}
              entries={entries}
              onNavigateToEntry={onNavigateToEntry}
              currentPageNumber={currentPageNumber}
            />
          ) : null}
        </div>
      )}

      {/* Floating bubble */}
      <button
        onClick={handleOpen}
        className={`fixed bottom-6 right-6 z-[90] w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-all hover:scale-105 ${
          isOpen ? "bg-gray-600 hover:bg-gray-700" : "bg-purple-600 hover:bg-purple-700"
        }`}
        title="AI Chat"
      >
        {isOpen ? <X size={22} className="text-white" /> : <Sparkles size={22} className="text-white" />}
        {!isOpen && (selectedEntry || selectedCollection || (pdfSelection?.text)) && (
          <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-green-500 rounded-full border-2 border-white dark:border-gray-900" />
        )}
      </button>
    </>
  );
}
