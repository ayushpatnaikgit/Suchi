import { useState, useEffect, useCallback } from "react";
import type { Entry } from "../../lib/types";
import { ExternalLink, Trash2, Tag, Calendar, BookOpen, User, Hash, FileText, ChevronDown, ChevronRight, CheckCircle, Search, Upload, Loader2, Quote, Compass, ArrowUpRight, ArrowDownRight, Sparkles, X, Plus, Library } from "lucide-react";
import { ReferencePopup } from "./ReferencePopup";

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

interface DiscoveredPaper {
  title: string;
  author: { given: string; family: string }[];
  year?: number;
  doi?: string;
  cited_by_count?: number;
  abstract?: string;
  venue?: string;
  in_library?: boolean;
  library_id?: string;
}

interface AuthorInfo {
  name: string;
  paper_count?: number;
  citation_count?: number;
  h_index?: number;
}

interface DiscoveryData {
  citing: DiscoveredPaper[];
  related: DiscoveredPaper[];
  author: { author: AuthorInfo | null; papers: DiscoveredPaper[] };
}

interface MetadataPanelProps {
  entry: Entry;
  onDelete: (id: string) => void;
  onViewPdf: (entry: Entry) => void;
  onNavigateToEntry?: (entryId: string) => void;
  onRefresh?: () => void;
}

function formatAuthors(authors: Entry["author"]): string {
  return authors.map((a) => `${a.given} ${a.family}`.trim()).join(", ");
}

export function MetadataPanel({ entry, onDelete, onViewPdf, onNavigateToEntry, onRefresh }: MetadataPanelProps) {
  const hasPdf = entry.files.some((f) => f.endsWith(".pdf"));
  const [findingPdf, setFindingPdf] = useState(false);
  const [pdfFound, setPdfFound] = useState<string | null>(null);  // source provider
  const [references, setReferences] = useState<Reference[]>([]);
  const [refsLoading, setRefsLoading] = useState(false);
  const [refsExpanded, setRefsExpanded] = useState(false);
  const [selectedRef, setSelectedRef] = useState<{ ref: Reference; x: number; y: number } | null>(null);

  // Discovery state
  const [discoverExpanded, setDiscoverExpanded] = useState(false);
  const [discovery, setDiscovery] = useState<DiscoveryData | null>(null);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverSection, setDiscoverSection] = useState<"citing" | "related" | "author">("citing");
  const [authorDialog, setAuthorDialog] = useState<{ author: AuthorInfo; papers: DiscoveredPaper[] } | null>(null);
  const [addingPaper, setAddingPaper] = useState<string | null>(null); // DOI being added

  // Load discovery data
  const loadDiscovery = useCallback(async () => {
    if (!entry.doi || discovery) return;
    setDiscoverLoading(true);
    try {
      const r = await fetch(`/api/discover/${encodeURIComponent(entry.id)}`);
      if (r.ok) {
        const data = await r.json();
        setDiscovery(data);
      }
    } catch (err) {
      console.error("Discovery failed:", err);
    } finally {
      setDiscoverLoading(false);
    }
  }, [entry.id, entry.doi, discovery]);

  // Load author papers dialog
  const loadAuthorPapers = useCallback(async (authorName: string) => {
    try {
      const r = await fetch(`/api/discover/${encodeURIComponent(entry.id)}/by-author?author=${encodeURIComponent(authorName)}&limit=20`);
      if (r.ok) {
        const data = await r.json();
        setAuthorDialog({ author: data.author, papers: data.papers });
      }
    } catch (err) {
      console.error("Author papers failed:", err);
    }
  }, [entry.id]);

  // Add a discovered paper to the library
  const addDiscoveredPaper = useCallback(async (paper: DiscoveredPaper) => {
    if (!paper.doi) return;
    setAddingPaper(paper.doi);
    try {
      const r = await fetch(`/api/entries/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: paper.doi,
          collections: entry.collections,
        }),
      });
      if (r.ok) {
        // Mark as in_library in our local state
        if (discovery) {
          const markInLib = (p: DiscoveredPaper) => {
            if (p.doi === paper.doi) { p.in_library = true; }
          };
          discovery.citing.forEach(markInLib);
          discovery.related.forEach(markInLib);
          discovery.author.papers.forEach(markInLib);
          setDiscovery({ ...discovery });
        }
        if (onRefresh) onRefresh();
      }
    } catch (err) {
      console.error("Add paper failed:", err);
    } finally {
      setAddingPaper(null);
    }
  }, [entry.collections, discovery, onRefresh]);

  // Load references automatically when a PDF entry is selected
  useEffect(() => {
    if (references.length === 0 && hasPdf) {
      setRefsLoading(true);
      fetch(`/api/references/${encodeURIComponent(entry.id)}`)
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => {
          console.log("References loaded:", data.count);
          setReferences(data.references || []);
        })
        .catch((err) => {
          console.error("Failed to load references:", err);
          setReferences([]);
        })
        .finally(() => setRefsLoading(false));
    }
  }, [entry.id, hasPdf]);

  // Reset when entry changes
  useEffect(() => {
    setReferences([]);
    setRefsExpanded(false);
    setSelectedRef(null);
    setPdfFound(null);
    setFindingPdf(false);
    setDiscovery(null);
    setDiscoverExpanded(false);
    setAuthorDialog(null);
  }, [entry.id]);

  const handleAddReference = async (doi: string | null, title: string | null, collections: string[]) => {
    const res = await fetch("/api/references/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doi, title, collections }),
    });
    if (!res.ok) throw new Error(await res.text());
    // Refresh references to update in_library status
    const refRes = await fetch(`/api/references/${encodeURIComponent(entry.id)}`);
    const data = await refRes.json();
    setReferences(data.references || []);
    if (onRefresh) onRefresh();
  };

  return (
    <div className="p-5 space-y-4 overflow-y-auto h-full bg-white dark:bg-gray-900">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 leading-snug">{entry.title}</h2>

      {entry.author.length > 0 && (
        <div className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-300">
          <User size={14} className="mt-0.5 flex-shrink-0 text-gray-400 dark:text-gray-500" />
          <span>{formatAuthors(entry.author)}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500 dark:text-gray-400">
        {entry.journal && <span className="flex items-center gap-1"><BookOpen size={12} /><em>{entry.journal}</em></span>}
        {entry.date && <span className="flex items-center gap-1"><Calendar size={12} />{entry.date}</span>}
        {entry.volume && <span>Vol. {entry.volume}{entry.issue && `(${entry.issue})`}</span>}
        {entry.pages && <span>pp. {entry.pages}</span>}
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        {hasPdf ? (
          <button onClick={() => onViewPdf(entry)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-suchi text-white rounded text-sm hover:bg-suchi-dark">
            <FileText size={14} />View PDF
          </button>
        ) : (
          <>
            {/* Find PDF button */}
            <button
              onClick={async () => {
                setFindingPdf(true);
                setPdfFound(null);
                try {
                  const resp = await fetch(`/api/pdf/download/${encodeURIComponent(entry.id)}`, { method: "POST" });
                  if (resp.ok) {
                    const data = await resp.json();
                    setPdfFound(data.provider || data.source || "found");
                    if (onRefresh) onRefresh();
                  } else {
                    setPdfFound("not_found");
                  }
                } catch {
                  setPdfFound("not_found");
                } finally {
                  setFindingPdf(false);
                }
              }}
              disabled={findingPdf || (!entry.doi && !entry.url)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded text-sm hover:bg-green-700 disabled:opacity-50"
            >
              {findingPdf ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              {findingPdf ? "Searching..." : pdfFound === "not_found" ? "No PDF Found" : "Find PDF"}
            </button>

            {/* Manual upload */}
            <label className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 cursor-pointer">
              <Upload size={14} />
              Add PDF
              <input
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const formData = new FormData();
                  formData.append("file", file);
                  await fetch(`/api/entries/${encodeURIComponent(entry.id)}/attach`, {
                    method: "POST",
                    body: formData,
                  });
                  if (onRefresh) onRefresh();
                }}
              />
            </label>

            {pdfFound && pdfFound !== "not_found" && (
              <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                <CheckCircle size={12} /> Downloaded from {pdfFound}
              </span>
            )}
          </>
        )}
        {entry.doi && (
          <a href={`https://doi.org/${entry.doi}`} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300">
            <ExternalLink size={14} />DOI
          </a>
        )}
        {entry.url && !entry.doi && (
          <a href={entry.url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 dark:border-gray-600 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300">
            <ExternalLink size={14} />Link
          </a>
        )}
        <button onClick={() => { if (confirm(`Delete "${entry.title}"?`)) onDelete(entry.id); }}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-red-200 dark:border-red-800 rounded text-sm hover:bg-red-50 dark:hover:bg-red-900/30 text-red-600 dark:text-red-400 ml-auto">
          <Trash2 size={14} />
        </button>
      </div>

      {/* Identifiers */}
      <div className="space-y-1.5 text-sm">
        {entry.doi && (
          <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
            <Hash size={12} className="text-gray-400 dark:text-gray-500" />
            <span className="font-mono text-xs">{entry.doi}</span>
          </div>
        )}
        {entry.isbn && (
          <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
            <Hash size={12} className="text-gray-400 dark:text-gray-500" />
            <span className="font-mono text-xs">ISBN: {entry.isbn}</span>
          </div>
        )}
      </div>

      {/* Tags */}
      {entry.tags.length > 0 && (
        <div>
          <div className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1.5">Tags</div>
          <div className="flex flex-wrap gap-1.5">
            {entry.tags.map((tag) => (
              <span key={tag} className="flex items-center gap-1 px-2 py-0.5 bg-suchi-50 dark:bg-suchi/20 text-suchi-700 dark:text-suchi-light rounded text-xs">
                <Tag size={10} />{tag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Abstract */}
      {entry.abstract && (
        <div>
          <div className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1.5">Abstract</div>
          <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{entry.abstract}</p>
        </div>
      )}

      {/* References */}
      {hasPdf && (
        <div>
          <button
            onClick={() => setRefsExpanded(!refsExpanded)}
            className="flex items-center gap-2 w-full px-3 py-2 -mx-3 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            {refsExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <BookOpen size={14} className="text-gray-400" />
            References
            {references.length > 0 && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">({references.length})</span>
            )}
            {!refsExpanded && references.length === 0 && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-normal ml-auto">Click to load</span>
            )}
          </button>

          {refsExpanded && (
            <div className="mt-2 space-y-0.5 max-h-[400px] overflow-y-auto">
              {refsLoading ? (
                <div className="text-sm text-gray-400 dark:text-gray-500 py-4 text-center">Extracting references from PDF...</div>
              ) : references.length === 0 ? (
                <div className="text-sm text-gray-400 dark:text-gray-500 py-4 text-center italic">No references found in this PDF</div>
              ) : (
                references.map((ref, i) => (
                  <button
                    key={i}
                    onClick={(e) => setSelectedRef({ ref, x: e.clientX, y: e.clientY })}
                    className="w-full text-left px-3 py-2 rounded-lg border border-transparent hover:border-gray-200 dark:hover:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm leading-snug transition-colors cursor-pointer"
                  >
                    <div className="flex items-start gap-2">
                      <span className="text-[10px] text-gray-400 dark:text-gray-600 font-mono mt-0.5 min-w-[20px]">{i + 1}</span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          {ref.in_library && <CheckCircle size={11} className="text-green-500 flex-shrink-0" />}
                          <span className={`font-medium ${ref.in_library ? "text-green-700 dark:text-green-400" : "text-gray-800 dark:text-gray-200"}`}>
                            {ref.title || ref.raw_text.slice(0, 80)}
                          </span>
                        </div>
                        <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 flex items-center flex-wrap gap-x-1.5">
                          {ref.authors_raw && <span>{ref.authors_raw.slice(0, 50)}</span>}
                          {ref.year && <span>{ref.authors_raw ? "·" : ""} {ref.year}</span>}
                          {typeof ref.cited_by_count === "number" && ref.cited_by_count > 0 && (
                            <span className="flex items-center gap-0.5 text-amber-600 dark:text-amber-500">
                              · <Quote size={9} />
                              {ref.cited_by_count.toLocaleString()}
                            </span>
                          )}
                          {ref.journal && <span className="italic text-gray-400 dark:text-gray-600">· {ref.journal.slice(0, 30)}</span>}
                          {ref.doi && <span>· DOI</span>}
                        </div>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      )}

      {/* Discovery */}
      {entry.doi && (
        <div>
          <button
            onClick={() => {
              setDiscoverExpanded(!discoverExpanded);
              if (!discoverExpanded && !discovery) loadDiscovery();
            }}
            className="flex items-center gap-2 w-full px-3 py-2 -mx-3 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            {discoverExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Compass size={14} className="text-indigo-400" />
            Discover
            {!discoverExpanded && !discovery && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-normal ml-auto">Click to load</span>
            )}
          </button>

          {discoverExpanded && (
            <div className="mt-2">
              {discoverLoading ? (
                <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-400">
                  <Loader2 size={14} className="animate-spin" /> Discovering related papers...
                </div>
              ) : discovery ? (
                <div>
                  {/* Section tabs */}
                  <div className="flex gap-1 mb-3">
                    {([
                      { key: "citing" as const, label: "Citing", icon: ArrowDownRight, count: discovery.citing.length, color: "text-green-500" },
                      { key: "related" as const, label: "Related", icon: Sparkles, count: discovery.related.length, color: "text-blue-500" },
                      { key: "author" as const, label: "By Author", icon: User, count: discovery.author.papers.length, color: "text-amber-500" },
                    ]).map(({ key, label, icon: Icon, count, color }) => (
                      <button
                        key={key}
                        onClick={() => setDiscoverSection(key)}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                          discoverSection === key
                            ? "bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                            : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
                        }`}
                      >
                        <Icon size={12} className={color} />
                        {label}
                        {count > 0 && <span className="text-[10px] text-gray-400">({count})</span>}
                      </button>
                    ))}
                  </div>

                  {/* Author info banner (for "By Author" tab) */}
                  {discoverSection === "author" && discovery.author.author && (
                    <div className="mb-3 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg text-xs">
                      <div className="font-medium text-amber-800 dark:text-amber-300">{discovery.author.author.name}</div>
                      <div className="text-amber-600 dark:text-amber-400 mt-0.5">
                        {discovery.author.author.paper_count} papers · {discovery.author.author.citation_count?.toLocaleString()} citations · h-index: {discovery.author.author.h_index}
                      </div>
                    </div>
                  )}

                  {/* Paper list */}
                  <div className="space-y-0.5 max-h-[400px] overflow-y-auto">
                    {(discoverSection === "citing" ? discovery.citing :
                      discoverSection === "related" ? discovery.related :
                      discovery.author.papers
                    ).map((paper, i) => (
                      <div
                        key={paper.doi || paper.title + i}
                        className="px-3 py-2 rounded-lg border border-transparent hover:border-gray-200 dark:hover:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm transition-colors"
                      >
                        <div className="flex items-start gap-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              {paper.in_library && <CheckCircle size={11} className="text-green-500 flex-shrink-0" />}
                              <span className={`font-medium leading-snug ${paper.in_library ? "text-green-700 dark:text-green-400" : "text-gray-800 dark:text-gray-200"}`}>
                                {paper.title.slice(0, 100)}
                              </span>
                            </div>
                            <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 flex items-center flex-wrap gap-x-1.5">
                              {paper.author?.length > 0 && (
                                <span>
                                  {paper.author.slice(0, 3).map((a, j) => (
                                    <button
                                      key={j}
                                      onClick={() => loadAuthorPapers(`${a.given} ${a.family}`.trim())}
                                      className="hover:text-[#5170FF] hover:underline cursor-pointer"
                                    >
                                      {a.family}{j < Math.min(paper.author.length, 3) - 1 ? ", " : ""}
                                    </button>
                                  ))}
                                  {paper.author.length > 3 && " et al."}
                                </span>
                              )}
                              {paper.year && <span>· {paper.year}</span>}
                              {typeof paper.cited_by_count === "number" && paper.cited_by_count > 0 && (
                                <span className="flex items-center gap-0.5 text-amber-600 dark:text-amber-500">
                                  · <Quote size={9} /> {paper.cited_by_count.toLocaleString()}
                                </span>
                              )}
                              {paper.venue && <span className="italic text-gray-400 dark:text-gray-600">· {paper.venue.slice(0, 25)}</span>}
                            </div>
                          </div>

                          {/* Add to library button */}
                          {!paper.in_library && paper.doi && (
                            <button
                              onClick={() => addDiscoveredPaper(paper)}
                              disabled={addingPaper === paper.doi}
                              className="flex-shrink-0 p-1 rounded hover:bg-[#5170FF]/10 text-gray-400 hover:text-[#5170FF] transition-colors"
                              title="Add to library"
                            >
                              {addingPaper === paper.doi ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <Plus size={14} />
                              )}
                            </button>
                          )}
                          {paper.in_library && paper.library_id && (
                            <button
                              onClick={() => onNavigateToEntry?.(paper.library_id!)}
                              className="flex-shrink-0 p-1 rounded hover:bg-green-500/10 text-green-500 transition-colors"
                              title="View in library"
                            >
                              <ExternalLink size={14} />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                    {((discoverSection === "citing" ? discovery.citing :
                       discoverSection === "related" ? discovery.related :
                       discovery.author.papers).length === 0) && (
                      <div className="py-4 text-sm text-gray-400 dark:text-gray-500 text-center italic">No papers found</div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="py-4 text-sm text-gray-400 text-center">No DOI available for discovery</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Author papers dialog */}
      {authorDialog && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setAuthorDialog(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <div>
                <div className="font-semibold text-gray-900 dark:text-gray-100">{authorDialog.author.name}</div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {authorDialog.author.paper_count} papers · {authorDialog.author.citation_count?.toLocaleString()} citations · h-index: {authorDialog.author.h_index}
                </div>
              </div>
              <button onClick={() => setAuthorDialog(null)} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                <X size={16} className="text-gray-400" />
              </button>
            </div>

            {/* Papers list */}
            <div className="overflow-y-auto max-h-[60vh] divide-y divide-gray-100 dark:divide-gray-700/50">
              {authorDialog.papers.map((paper, i) => (
                <div key={paper.doi || i} className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-gray-800 dark:text-gray-200 leading-snug">
                        {paper.title.slice(0, 100)}
                      </div>
                      <div className="text-xs text-gray-400 dark:text-gray-500 mt-1 flex items-center gap-1.5">
                        {paper.year && <span>{paper.year}</span>}
                        {typeof paper.cited_by_count === "number" && paper.cited_by_count > 0 && (
                          <span className="flex items-center gap-0.5 text-amber-600 dark:text-amber-500">
                            · <Quote size={9} /> {paper.cited_by_count.toLocaleString()}
                          </span>
                        )}
                        {paper.venue && <span className="italic">· {paper.venue.slice(0, 30)}</span>}
                      </div>
                    </div>

                    {!paper.in_library && paper.doi ? (
                      <button
                        onClick={() => addDiscoveredPaper(paper)}
                        disabled={addingPaper === paper.doi}
                        className="flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded text-xs bg-[#5170FF] text-white hover:bg-[#3d5ce0] disabled:opacity-50 transition-colors"
                      >
                        {addingPaper === paper.doi ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                        Add
                      </button>
                    ) : paper.in_library ? (
                      <span className="flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20">
                        <CheckCircle size={12} /> In library
                      </span>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Files */}
      {entry.files.length > 0 && (
        <div>
          <div className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1.5">Files</div>
          <div className="space-y-1">
            {entry.files.map((f) => (
              <div key={f} className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 font-mono"><FileText size={12} />{f}</div>
            ))}
          </div>
        </div>
      )}

      {/* Metadata footer */}
      <div className="pt-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400 dark:text-gray-500 space-y-0.5">
        {entry.added && <div>Added: {new Date(entry.added).toLocaleDateString()}</div>}
        {entry.modified && <div>Modified: {new Date(entry.modified).toLocaleDateString()}</div>}
        <div className="font-mono">{entry.id}</div>
      </div>

      {/* Reference popup */}
      {selectedRef && (
        <ReferencePopup
          reference={selectedRef.ref}
          currentCollections={entry.collections}
          position={{ x: selectedRef.x, y: selectedRef.y }}
          onClose={() => setSelectedRef(null)}
          onAddToLibrary={handleAddReference}
          onNavigateToEntry={(id) => {
            setSelectedRef(null);
            if (onNavigateToEntry) onNavigateToEntry(id);
          }}
        />
      )}
    </div>
  );
}
