import { useState, useRef, useEffect, useMemo } from "react";
import { Send, X, Bot, User, Sparkles, FileText, FolderOpen, MessageSquareQuote } from "lucide-react";
import Markdown from "react-markdown";
import type { Entry } from "../../lib/types";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatContext {
  type: "paper" | "collection" | "selection" | "general";
  entryId?: string;
  collectionId?: string;
  selectedText?: string;
  entryIdForSelection?: string;
  label: string;
}

interface ChatPanelProps {
  context: ChatContext;
  onClose: () => void;
  onChangeContext?: () => void;
  entries?: Entry[];
  onNavigateToEntry?: (entryId: string) => void;
  currentPageNumber?: number;
}

export function ChatPanel({ context, onClose, onChangeContext, entries = [], onNavigateToEntry, currentPageNumber }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Reset chat when context changes
  useEffect(() => {
    setMessages([]);
    setError(null);
  }, [context.entryId, context.collectionId, context.selectedText]);

  const handleSend = async (overrideText?: string) => {
    const text = (overrideText || input).trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);
    setError(null);

    // Build request body
    const body: Record<string, unknown> = {
      message: text,
      history: messages,
    };
    if (context.type === "paper" && context.entryId) {
      body.entry_id = context.entryId;
      // Send current PDF page number for visual context
      if (currentPageNumber && currentPageNumber > 0) {
        body.page_number = currentPageNumber;
      }
    } else if (context.type === "collection" && context.collectionId) {
      body.collection_id = context.collectionId;
    } else if (context.type === "selection" && context.selectedText) {
      body.selected_text = context.selectedText;
      body.entry_id_for_selection = context.entryIdForSelection;
      // Also send the page for visual context
      if (currentPageNumber && currentPageNumber > 0) {
        body.page_number = currentPageNumber;
      }
    }

    // Stream response
    const assistantMsg: ChatMessage = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) throw new Error("No response stream");

      let fullText = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            if (data === "[DONE]") break;
            try {
              const parsed = JSON.parse(data);
              if (parsed.error) {
                throw new Error(parsed.error);
              }
              if (parsed.text) {
                fullText += parsed.text;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: "assistant", content: fullText };
                  return updated;
                });
              }
            } catch (e) {
              if (e instanceof Error && e.message !== data) throw e;
            }
          }
        }
      }
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : "Chat failed";
      setError(errMsg);
      // Remove the empty assistant message
      setMessages((prev) => {
        if (prev[prev.length - 1]?.content === "") {
          return prev.slice(0, -1);
        }
        return prev;
      });
    } finally {
      setStreaming(false);
    }
  };

  const contextIcon = {
    paper: <FileText size={14} />,
    collection: <FolderOpen size={14} />,
    selection: <MessageSquareQuote size={14} />,
    general: <Sparkles size={14} />,
  }[context.type];

  // Build title → entry ID lookup for paper linking
  const titleMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of entries) {
      map.set(e.title.toLowerCase(), e.id);
    }
    return map;
  }, [entries]);

  /** Render markdown text with [[Paper Title]] as clickable links.
   * First resolve [[...]] links, then render the result as markdown. */
  const renderMarkdownWithLinks = (text: string) => {
    // Replace [[Paper Title]] with clickable markdown-style links
    const linkedText = text.replace(/\[\[(.*?)\]\]/g, (_match, title) => {
      const entryId = titleMap.get(title.toLowerCase());
      if (entryId) {
        // Use a custom protocol that we'll intercept in the markdown renderer
        return `[${title}](cloudref://entry/${entryId})`;
      }
      return `**${title}**`;
    });

    return (
      <Markdown
        components={{
          a: ({ href, children }) => {
            // Handle cloudref:// links (paper references)
            if (href?.startsWith("cloudref://entry/")) {
              const entryId = href.replace("cloudref://entry/", "");
              return (
                <button
                  onClick={() => onNavigateToEntry?.(entryId)}
                  className="text-purple-600 dark:text-purple-400 underline decoration-purple-300 dark:decoration-purple-700 underline-offset-2 hover:text-purple-800 dark:hover:text-purple-300 cursor-pointer font-medium"
                >
                  {children}
                </button>
              );
            }
            // External links
            return (
              <a href={href} target="_blank" rel="noopener noreferrer"
                className="text-blue-600 dark:text-blue-400 underline">{children}</a>
            );
          },
          // Style headings
          h1: ({ children }) => <h1 className="text-base font-bold mt-3 mb-1">{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-bold mt-2.5 mb-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-0.5">{children}</h3>,
          // Style lists
          ul: ({ children }) => <ul className="list-disc pl-4 my-1 space-y-0.5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-4 my-1 space-y-0.5">{children}</ol>,
          li: ({ children }) => <li className="text-sm">{children}</li>,
          // Style code blocks
          code: ({ className, children }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <code className="block bg-gray-200 dark:bg-gray-700 rounded px-2 py-1.5 my-1 text-xs font-mono overflow-x-auto whitespace-pre">
                  {children}
                </code>
              );
            }
            return (
              <code className="bg-gray-200 dark:bg-gray-700 rounded px-1 py-0.5 text-xs font-mono">
                {children}
              </code>
            );
          },
          // Style paragraphs
          p: ({ children }) => <p className="my-1">{children}</p>,
          // Style bold/italic
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          // Style blockquotes
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-purple-400 dark:border-purple-600 pl-3 my-1 italic text-gray-600 dark:text-gray-400">
              {children}
            </blockquote>
          ),
        }}
      >
        {linkedText}
      </Markdown>
    );
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-purple-500" />
          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">AI Assistant</span>
          <button
            onClick={onChangeContext}
            className="flex items-center gap-1 px-2 py-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded text-xs hover:bg-purple-100 dark:hover:bg-purple-900/50 transition-colors"
            title="Change context"
          >
            {contextIcon}
            {context.label}
          </button>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400">
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-12">
            <Sparkles size={32} className="mx-auto text-purple-300 dark:text-purple-600 mb-3" />
            <div className="text-sm text-gray-500 dark:text-gray-400 mb-2">
              {context.type === "paper" && "Ask anything about this paper"}
              {context.type === "collection" && "Ask about papers in this collection"}
              {context.type === "selection" && "Ask about the selected text"}
              {context.type === "general" && "Ask anything about your research"}
            </div>
            <div className="flex flex-wrap gap-2 justify-center mt-4">
              {context.type === "paper" && (
                <>
                  <SuggestionChip text="Summarize this paper" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="What are the key findings?" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="Explain the methodology" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="What are the limitations?" onClick={(t) => { handleSend(t); }} />
                </>
              )}
              {context.type === "collection" && (
                <>
                  <SuggestionChip text="Summarize the key themes" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="Compare the methodologies" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="What gaps exist in this research?" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="Generate a literature review outline" onClick={(t) => { handleSend(t); }} />
                </>
              )}
              {context.type === "selection" && (
                <>
                  <SuggestionChip text="Explain this in simple terms" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="What does this mean?" onClick={(t) => { handleSend(t); }} />
                  <SuggestionChip text="Why is this important?" onClick={(t) => { handleSend(t); }} />
                </>
              )}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && (
              <div className="w-7 h-7 rounded-full bg-purple-100 dark:bg-purple-900/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                <Bot size={14} className="text-purple-600 dark:text-purple-400" />
              </div>
            )}
            <div
              className={`max-w-[80%] px-3 py-2 rounded-lg text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-blue-600 text-white rounded-br-sm"
                  : "bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded-bl-sm"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="prose-sm dark:prose-invert max-w-none">
                  {msg.content ? renderMarkdownWithLinks(msg.content) : (streaming && i === messages.length - 1 ? <span className="animate-pulse">●●●</span> : "")}
                </div>
              ) : (
                <div className="whitespace-pre-wrap">{msg.content}</div>
              )}
            </div>
            {msg.role === "user" && (
              <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center flex-shrink-0 mt-0.5">
                <User size={14} className="text-blue-600 dark:text-blue-400" />
              </div>
            )}
          </div>
        ))}

        {error && (
          <div className="px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Selected text preview */}
      {context.type === "selection" && context.selectedText && messages.length === 0 && (
        <div className="px-4 pb-2">
          <div className="px-3 py-2 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded text-xs text-gray-600 dark:text-gray-400 max-h-20 overflow-y-auto">
            <span className="font-medium text-yellow-700 dark:text-yellow-400">Selected: </span>
            {context.selectedText.slice(0, 300)}{context.selectedText.length > 300 ? "..." : ""}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about your research..."
            rows={1}
            className="flex-1 resize-none border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm outline-none focus:border-purple-400 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 max-h-32"
            style={{ minHeight: "38px" }}
            disabled={streaming}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            className="p-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

function SuggestionChip({ text, onClick }: { text: string; onClick: (text: string) => void }) {
  return (
    <button
      onClick={() => onClick(text)}
      className="px-3 py-1.5 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 rounded-full text-xs transition-colors"
    >
      {text}
    </button>
  );
}
