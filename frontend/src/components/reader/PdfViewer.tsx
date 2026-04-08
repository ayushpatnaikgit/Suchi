import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ZoomIn, ZoomOut, X, Highlighter } from "lucide-react";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { ReferencePopup } from "../metadata/ReferencePopup";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

// --- Types ---

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

interface Annotation {
  id: string;
  page: number;
  type: "highlight" | "note";
  color: string;
  text: string;        // The highlighted text or note content
  rects: { x: number; y: number; w: number; h: number }[]; // Normalized 0-1 coords
  created: string;
}

interface PdfViewerProps {
  url: string;
  title: string;
  entryId: string;
  currentCollections?: string[];
  onClose: () => void;
  onTextSelected: (text: string, entryId: string) => void;
  onNavigateToEntry?: (entryId: string) => void;
  onPageChange?: (page: number) => void;
  initialPage?: number; // Restored from last session
}

// --- Utility functions for reference matching (unchanged) ---

function parseRefIndexFromDest(dest: string | any[] | null): number | null {
  if (!dest) return null;
  const destStr = typeof dest === "string" ? dest : null;
  if (!destStr) return null;
  if (/^cite\.[a-z]+\d{4}/i.test(destStr)) return null;
  const patterns = [
    /^bib\.?bib(\d+)$/i, /^bibr?\.?(\d+)$/i, /^cite\.?cite?(\d+)$/i,
    /^ref\.?(\d+)$/i, /^reference[._-]?(\d+)$/i, /^R(\d+)$/, /^(\d+)$/,
  ];
  for (const pattern of patterns) {
    const match = destStr.match(pattern);
    if (match) {
      const idx = parseInt(match[1], 10);
      if (idx > 0 && idx < 1000) return idx;
    }
  }
  return null;
}

function matchRefByBibkey(dest: string | any[] | null, references: Reference[]): Reference | null {
  if (typeof dest !== "string") return null;
  const m = dest.match(/^(?:cite|ref|bib)\.?([a-z][a-z]+?)[\s_-]?(\d{4})[\s_-]?([a-z]*)$/i);
  if (!m) return null;
  const [, author, year, keyword] = m;
  const authorLower = author.toLowerCase();
  const matches = references.filter((ref) => {
    const refYear = ref.year || "";
    if (refYear !== year) return false;
    const refAuthors = (ref.authors_raw || "").toLowerCase();
    return refAuthors.includes(authorLower);
  });
  if (matches.length === 1) return matches[0];
  if (matches.length > 1 && keyword) {
    const keyLower = keyword.toLowerCase();
    const keyMatch = matches.find((r) => (r.title || "").toLowerCase().includes(keyLower));
    if (keyMatch) return keyMatch;
  }
  return matches[0] || null;
}

async function matchRefByPosition(pdfDoc: any, dest: any, references: Reference[]): Promise<Reference | null> {
  try {
    let explicitDest = dest;
    if (typeof dest === "string") {
      explicitDest = await pdfDoc.getDestination(dest);
    }
    if (!Array.isArray(explicitDest)) return null;
    const destRef = explicitDest[0];
    let pageIdx: number;
    if (typeof destRef === "number") {
      pageIdx = destRef;
    } else {
      pageIdx = await pdfDoc.getPageIndex(destRef);
    }
    const page = await pdfDoc.getPage(pageIdx + 1);
    const textContent = await page.getTextContent();
    const items = textContent.items as any[];
    const y = explicitDest[3];
    const nearbyText = items
      .filter((item: any) => {
        const itemY = item.transform?.[5];
        return typeof itemY === "number" && Math.abs(itemY - y) < 30;
      })
      .map((item: any) => item.str)
      .join(" ")
      .toLowerCase()
      .slice(0, 200);
    if (!nearbyText) return null;
    let bestMatch: Reference | null = null;
    let bestScore = 0;
    for (const ref of references) {
      const refTitle = (ref.title || "").toLowerCase();
      const refAuthors = (ref.authors_raw || "").toLowerCase().split(",")[0];
      let score = 0;
      if (refTitle) {
        const titleWords = refTitle.split(/\s+/).filter((w) => w.length > 3);
        const matched = titleWords.filter((w) => nearbyText.includes(w));
        score = matched.length / Math.max(titleWords.length, 1);
      }
      if (refAuthors && nearbyText.includes(refAuthors.slice(0, 8))) {
        score += 0.3;
      }
      if (score > bestScore && score > 0.3) {
        bestScore = score;
        bestMatch = ref;
      }
    }
    return bestMatch;
  } catch {
    return null;
  }
}

// --- Highlight colors ---
const HIGHLIGHT_COLORS = [
  { name: "Yellow", value: "rgba(255, 235, 59, 0.4)", border: "#fdd835" },
  { name: "Green", value: "rgba(76, 175, 80, 0.35)", border: "#43a047" },
  { name: "Blue", value: "rgba(66, 165, 245, 0.35)", border: "#1e88e5" },
  { name: "Pink", value: "rgba(236, 64, 122, 0.3)", border: "#d81b60" },
  { name: "Orange", value: "rgba(255, 152, 0, 0.35)", border: "#f57c00" },
];

// --- Main component ---

export function PdfViewer({
  url,
  title,
  entryId,
  currentCollections = [],
  onClose,
  onTextSelected,
  onNavigateToEntry,
  onPageChange,
  initialPage = 1,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState(initialPage);
  const [scale, setScale] = useState(1.0);
  const [references, setReferences] = useState<Reference[]>([]);
  const [clickedRef, setClickedRef] = useState<{ ref: Reference; x: number; y: number } | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [highlightMode, setHighlightMode] = useState(false);
  const [highlightColor, setHighlightColor] = useState(HIGHLIGHT_COLORS[0].value);
  const [showColorPicker, setShowColorPicker] = useState(false);

  const pdfDocRef = useRef<any>(null);
  const documentInstanceRef = useRef<any>(null);
  const linkServicePatchedRef = useRef(false);
  const lastDestStringRef = useRef<string | null>(null);
  const lastClickRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const referencesRef = useRef<Reference[]>([]);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const isScrollingRef = useRef(false);
  const savedPageRef = useRef(initialPage);

  useEffect(() => {
    referencesRef.current = references;
  }, [references]);

  // Load references for this entry
  useEffect(() => {
    fetch(`/api/references/${encodeURIComponent(entryId)}`)
      .then((r) => r.json())
      .then((d) => setReferences(d.references || []))
      .catch(() => {});
  }, [entryId]);

  // Load annotations for this entry
  useEffect(() => {
    fetch(`/api/entries/${encodeURIComponent(entryId)}/annotations`)
      .then((r) => r.ok ? r.json() : [])
      .then((a) => setAnnotations(a || []))
      .catch(() => {});
  }, [entryId]);

  // Scroll to initial page when PDF loads
  useEffect(() => {
    if (numPages > 0 && initialPage > 1) {
      // Small delay to let pages render
      setTimeout(() => {
        const pageEl = pageRefs.current.get(initialPage);
        if (pageEl) {
          isScrollingRef.current = true;
          pageEl.scrollIntoView({ behavior: "auto" });
          setTimeout(() => { isScrollingRef.current = false; }, 200);
        }
      }, 500);
    }
  }, [numPages, initialPage]);

  // Track current page based on scroll position
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || numPages === 0) return;

    let ticking = false;
    const handleScroll = () => {
      if (ticking || isScrollingRef.current) return;
      ticking = true;
      requestAnimationFrame(() => {
        const containerRect = container.getBoundingClientRect();
        const containerCenter = containerRect.top + containerRect.height / 2;
        let closestPage = 1;
        let closestDist = Infinity;

        pageRefs.current.forEach((el, pageNum) => {
          const rect = el.getBoundingClientRect();
          const pageCenter = rect.top + rect.height / 2;
          const dist = Math.abs(pageCenter - containerCenter);
          if (dist < closestDist) {
            closestDist = dist;
            closestPage = pageNum;
          }
        });

        if (closestPage !== currentPage) {
          setCurrentPage(closestPage);
          savedPageRef.current = closestPage;
          onPageChange?.(closestPage);
        }
        ticking = false;
      });
    };

    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, [numPages, currentPage, onPageChange]);

  // Save last page on unmount
  useEffect(() => {
    return () => {
      // Persist the last viewed page
      fetch(`/api/entries/${encodeURIComponent(entryId)}/last-page`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: savedPageRef.current }),
      }).catch(() => {});
    };
  }, [entryId]);

  // Register page refs
  const setPageRef = useCallback((pageNum: number) => (el: HTMLDivElement | null) => {
    if (el) {
      pageRefs.current.set(pageNum, el);
    } else {
      pageRefs.current.delete(pageNum);
    }
  }, []);

  // Text selection handling
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    lastClickRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (text && text.length > 2) {
      if (highlightMode) {
        // Create highlight annotation
        createHighlight(text);
      } else {
        onTextSelected(text, entryId);
      }
    }
  }, [entryId, onTextSelected, highlightMode, highlightColor]);

  // Create a highlight annotation from selected text
  const createHighlight = useCallback(async (text: string) => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;

    // Determine which page the selection is on
    const range = sel.getRangeAt(0);
    const rects = Array.from(range.getClientRects());
    if (rects.length === 0) return;

    // Find the page element containing the selection
    let pageNum = currentPage;
    const startNode = range.startContainer.parentElement;
    if (startNode) {
      const pageEl = startNode.closest("[data-page-number]");
      if (pageEl) {
        pageNum = parseInt(pageEl.getAttribute("data-page-number") || "1", 10);
      }
    }

    // Normalize rects relative to the page
    const pageEl = pageRefs.current.get(pageNum);
    if (!pageEl) return;
    const pageRect = pageEl.getBoundingClientRect();

    const normalizedRects = rects.map((r) => ({
      x: (r.left - pageRect.left) / pageRect.width,
      y: (r.top - pageRect.top) / pageRect.height,
      w: r.width / pageRect.width,
      h: r.height / pageRect.height,
    }));

    const annotation: Annotation = {
      id: `hl-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      page: pageNum,
      type: "highlight",
      color: highlightColor,
      text,
      rects: normalizedRects,
      created: new Date().toISOString(),
    };

    setAnnotations((prev) => [...prev, annotation]);

    // Persist to backend
    try {
      await fetch(`/api/entries/${encodeURIComponent(entryId)}/annotations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(annotation),
      });
    } catch {
      // Annotation saved locally even if backend fails
    }

    sel.removeAllRanges();
  }, [currentPage, entryId, highlightColor]);

  // Delete annotation
  const deleteAnnotation = useCallback(async (id: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== id));
    try {
      await fetch(`/api/entries/${encodeURIComponent(entryId)}/annotations/${id}`, { method: "DELETE" });
    } catch {}
  }, [entryId]);

  // Reference matching
  const tryMatchReference = useCallback(
    async (destString: string | null, destArray: any[] | null): Promise<Reference | null> => {
      const refs = referencesRef.current;
      if (refs.length === 0) return null;
      if (destString) {
        const parsedIdx = parseRefIndexFromDest(destString);
        if (parsedIdx !== null && parsedIdx <= refs.length) return refs[parsedIdx - 1];
        const bibkeyMatch = matchRefByBibkey(destString, refs);
        if (bibkeyMatch) return bibkeyMatch;
      }
      if (pdfDocRef.current) {
        const destForPos = destArray || destString;
        if (destForPos) {
          const matched = await matchRefByPosition(pdfDocRef.current, destForPos, refs);
          if (matched) return matched;
        }
      }
      return null;
    },
    []
  );

  // Go to page — scroll a specific page into view
  const goToPage = useCallback((page: number) => {
    const el = pageRefs.current.get(page);
    if (el) {
      isScrollingRef.current = true;
      el.scrollIntoView({ behavior: "smooth" });
      setCurrentPage(page);
      setTimeout(() => { isScrollingRef.current = false; }, 600);
    }
  }, []);

  const handleItemClick = useCallback(
    async (args: any) => {
      const { dest, pageNumber } = args;
      const { x, y } = lastClickRef.current;
      const destString = lastDestStringRef.current;
      lastDestStringRef.current = null;

      // Navigate to the target page
      if (pageNumber) goToPage(pageNumber);

      const matched = await tryMatchReference(destString, Array.isArray(dest) ? dest : null);
      if (matched) {
        setClickedRef({ ref: matched, x, y });
        return;
      }
      setClickedRef({
        ref: { raw_text: `Could not match reference${destString ? ` (dest: ${destString})` : ""}`, in_library: false } as Reference,
        x, y,
      });
    },
    [tryMatchReference, goToPage]
  );

  const handleAddToLibrary = async (doi: string | null, refTitle: string | null, collections: string[]) => {
    await fetch("/api/references/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doi, title: refTitle, collections, tags: [] }),
    });
    const refRes = await fetch(`/api/references/${encodeURIComponent(entryId)}`);
    const data = await refRes.json();
    setReferences(data.references || []);
  };

  // Page numbers array
  const pageNumbers = useMemo(() => {
    return Array.from({ length: numPages }, (_, i) => i + 1);
  }, [numPages]);

  // Annotations for a given page
  const getPageAnnotations = useCallback(
    (pageNum: number) => annotations.filter((a) => a.page === pageNum),
    [annotations]
  );

  return (
    <div className="flex flex-col h-full bg-gray-100 dark:bg-gray-950">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
        <div className="text-sm font-medium text-gray-700 dark:text-gray-200 truncate max-w-[300px]">{title}</div>
        <div className="flex items-center gap-1.5">
          {/* Page indicator */}
          <span className="text-xs text-gray-500 dark:text-gray-400 min-w-[60px] text-center">
            {currentPage} / {numPages}
          </span>
          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600 mx-1" />

          {/* Zoom */}
          <button onClick={() => setScale((s) => Math.max(0.5, s - 0.15))}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300">
            <ZoomOut size={15} />
          </button>
          <span className="text-xs text-gray-500 dark:text-gray-400 min-w-[35px] text-center">{Math.round(scale * 100)}%</span>
          <button onClick={() => setScale((s) => Math.min(3, s + 0.15))}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300">
            <ZoomIn size={15} />
          </button>
          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600 mx-1" />

          {/* Highlight mode toggle */}
          <button
            onClick={() => setHighlightMode(!highlightMode)}
            className={`p-1.5 rounded transition-colors ${
              highlightMode
                ? "bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-400 ring-1 ring-yellow-400"
                : "hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300"
            }`}
            title={highlightMode ? "Disable highlight mode" : "Enable highlight mode"}
          >
            <Highlighter size={15} />
          </button>

          {/* Color picker */}
          {highlightMode && (
            <div className="relative">
              <button
                onClick={() => setShowColorPicker(!showColorPicker)}
                className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
                title="Highlight color"
              >
                <div className="w-4 h-4 rounded-sm border border-gray-300 dark:border-gray-600"
                  style={{ backgroundColor: highlightColor }} />
              </button>
              {showColorPicker && (
                <div className="absolute top-full right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl p-2 flex gap-1.5 z-50">
                  {HIGHLIGHT_COLORS.map((c) => (
                    <button
                      key={c.name}
                      onClick={() => { setHighlightColor(c.value); setShowColorPicker(false); }}
                      className={`w-6 h-6 rounded-full border-2 transition-transform ${
                        highlightColor === c.value ? "border-gray-800 dark:border-white scale-110" : "border-transparent"
                      }`}
                      style={{ backgroundColor: c.value }}
                      title={c.name}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="w-px h-4 bg-gray-300 dark:bg-gray-600 mx-1" />
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* PDF content — continuous scroll, all pages rendered */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-auto"
        onMouseUp={handleMouseUp}
        onMouseDown={handleMouseDown}
        style={{ cursor: highlightMode ? "text" : "default" }}
      >
        <Document
          file={url}
          ref={(instance: any) => {
            documentInstanceRef.current = instance;
            const linkService = instance?.linkService?.current;
            if (linkService && !linkServicePatchedRef.current) {
              const originalGoTo = linkService.goToDestination.bind(linkService);
              linkService.goToDestination = (dest: any) => {
                if (typeof dest === "string") {
                  lastDestStringRef.current = dest;
                }
                return originalGoTo(dest);
              };
              linkServicePatchedRef.current = true;
            }
          }}
          onLoadSuccess={(pdf: any) => {
            setNumPages(pdf.numPages);
            pdfDocRef.current = pdf;
          }}
          onItemClick={handleItemClick as any}
          loading={<div className="flex items-center justify-center h-64 text-gray-400 dark:text-gray-500 text-sm">Loading PDF...</div>}
          error={<div className="flex items-center justify-center h-64 text-red-400 text-sm">Failed to load PDF</div>}
        >
          <div className="flex flex-col items-center gap-4 py-4">
            {pageNumbers.map((pageNum) => (
              <div key={pageNum} ref={setPageRef(pageNum)} className="relative" data-page-number={pageNum}>
                <Page
                  pageNumber={pageNum}
                  scale={scale}
                  className="shadow-lg"
                  renderAnnotationLayer={true}
                  renderTextLayer={true}
                />

                {/* Highlight overlay for this page */}
                {getPageAnnotations(pageNum).map((ann) => (
                  <div key={ann.id} className="absolute inset-0 pointer-events-none" style={{ zIndex: 10 }}>
                    {ann.rects.map((rect, ri) => (
                      <div
                        key={ri}
                        className="absolute pointer-events-auto cursor-pointer group"
                        style={{
                          left: `${rect.x * 100}%`,
                          top: `${rect.y * 100}%`,
                          width: `${rect.w * 100}%`,
                          height: `${rect.h * 100}%`,
                          backgroundColor: ann.color,
                          mixBlendMode: "multiply",
                        }}
                        title={`"${ann.text.slice(0, 60)}..." — Click to delete`}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`Delete this highlight?\n\n"${ann.text.slice(0, 100)}..."`)) {
                            deleteAnnotation(ann.id);
                          }
                        }}
                      >
                        <div className="absolute -top-5 left-0 hidden group-hover:block bg-gray-900 text-white text-xs px-1.5 py-0.5 rounded whitespace-nowrap z-50">
                          {ann.text.slice(0, 40)}{ann.text.length > 40 ? "..." : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Document>
      </div>

      {/* Reference popup */}
      {clickedRef && (
        <ReferencePopup
          reference={clickedRef.ref}
          currentCollections={currentCollections}
          position={{ x: clickedRef.x, y: clickedRef.y }}
          onClose={() => setClickedRef(null)}
          onAddToLibrary={handleAddToLibrary}
          onNavigateToEntry={(id) => {
            setClickedRef(null);
            onNavigateToEntry?.(id);
          }}
        />
      )}
    </div>
  );
}
