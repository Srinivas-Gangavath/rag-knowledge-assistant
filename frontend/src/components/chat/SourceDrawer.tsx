import { useEffect, useState, useRef } from "react";
import type { ChatSource, DocumentSourceEvidence } from "../../types";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../ui";

type SourceDrawerProps = {
  isOpen: boolean;
  onClose: () => void;
  sources: ChatSource[];
  activeSourceIndex: number | null;
  onSelectSource: (index: number) => void;
};

// Transient in-memory cache for loaded source evidence across the active conversation session.
// Strictly non-persistent, tenant-scoped, and cleared upon auth/workspace transitions.
const evidenceCache = new Map<string, DocumentSourceEvidence>();

export function clearSourceEvidenceCache(): void {
  evidenceCache.clear();
}

function buildCacheKey(
  orgId: string | undefined,
  wsId: string | undefined,
  userId: string | undefined,
  docId: string,
  chunkIdx: number
): string {
  return `${orgId || "no-org"}:${wsId || "no-ws"}:${userId || "anon"}:${docId}:${chunkIdx}`;
}

export function SourceDrawer({
  isOpen,
  onClose,
  sources,
  activeSourceIndex,
  onSelectSource,
}: SourceDrawerProps) {
  const { user, activeWorkspace } = useAuth();
  const [evidence, setEvidence] = useState<DocumentSourceEvidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const currentIndex =
    activeSourceIndex !== null && activeSourceIndex >= 0 && activeSourceIndex < sources.length
      ? activeSourceIndex
      : 0;

  const currentSource = sources[currentIndex];

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && isOpen) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Focus close button on drawer open for accessibility
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => closeButtonRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Load source evidence for the active source
  useEffect(() => {
    if (!isOpen || !currentSource) {
      setEvidence(null);
      setError(null);
      setLoading(false);
      return;
    }

    const cacheKey = buildCacheKey(
      activeWorkspace?.organization_id,
      activeWorkspace?.id,
      user?.id,
      currentSource.document_id,
      currentSource.chunk_index
    );

    if (evidenceCache.has(cacheKey)) {
      setEvidence(evidenceCache.get(cacheKey)!);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setEvidence(null);

    api
      .getDocumentSourceEvidence(currentSource.document_id, currentSource.chunk_index)
      .then((data) => {
        if (!cancelled) {
          evidenceCache.set(cacheKey, data);
          setEvidence(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(userFacingError(err, "list"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, currentSource, activeWorkspace?.organization_id, activeWorkspace?.id, user?.id]);

  function handleCopyPassage() {
    if (!evidence?.content) return;
    navigator.clipboard.writeText(evidence.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function handleRetry() {
    if (!currentSource) return;
    const cacheKey = buildCacheKey(
      activeWorkspace?.organization_id,
      activeWorkspace?.id,
      user?.id,
      currentSource.document_id,
      currentSource.chunk_index
    );
    evidenceCache.delete(cacheKey);
    setLoading(true);
    setError(null);

    api
      .getDocumentSourceEvidence(currentSource.document_id, currentSource.chunk_index)
      .then((data) => {
        evidenceCache.set(cacheKey, data);
        setEvidence(data);
      })
      .catch((err) => {
        setError(userFacingError(err, "list"));
      })
      .finally(() => {
        setLoading(false);
      });
  }

  if (!isOpen || sources.length === 0 || !currentSource) return null;

  return (
    <>
      {/* Mobile Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-xs md:hidden"
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col bg-white border-l border-slate-200 shadow-2xl transition-transform duration-200 ease-in-out sm:w-96"
        role="dialog"
        aria-label="Source Inspector"
        aria-modal="true"
      >
        {/* 1. Header */}
        <div className="flex items-center justify-between border-b border-slate-200/90 px-4 py-3.5 bg-slate-50/70">
          <div className="flex items-center gap-2 min-w-0">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-100 text-brand-700 text-xs font-bold">
              [{currentIndex + 1}]
            </span>
            <div className="min-w-0">
              <h3 className="text-xs font-semibold text-slate-900">Source Inspector</h3>
              <p className="text-[11px] text-slate-500 truncate">
                Source {currentIndex + 1} of {sources.length}
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close source inspector"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 focus:outline-none focus:ring-1 focus:ring-brand-500 cursor-pointer"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 2. Multi-Source Tabs (if multiple sources exist) */}
        {sources.length > 1 && (
          <div className="flex items-center gap-1.5 border-b border-slate-200 bg-white px-3 py-2 overflow-x-auto" role="tablist">
            {sources.map((src, idx) => (
              <button
                key={`${src.document_id}-${src.chunk_index}-${idx}`}
                type="button"
                role="tab"
                aria-selected={idx === currentIndex}
                onClick={() => onSelectSource(idx)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors shrink-0 cursor-pointer ${
                  idx === currentIndex
                    ? "bg-brand-600 text-white shadow-xs"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
                }`}
              >
                Source [{idx + 1}]
              </button>
            ))}
          </div>
        )}

        {/* 3. Source Evidence Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
          {/* Document & Page Metadata */}
          <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5 space-y-3">
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Document Name</dt>
              <dd className="mt-0.5 font-semibold text-slate-900 break-words text-xs">
                {evidence?.filename || currentSource.filename}
              </dd>
            </div>

            <div className="grid grid-cols-2 gap-2 border-t border-slate-200/60 pt-2.5">
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Page Location</dt>
                <dd className="mt-0.5 font-medium text-slate-800">
                  {currentSource.page_number != null ? `Page ${currentSource.page_number}` : "Page not available"}
                </dd>
              </div>

              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Chunk Reference</dt>
                <dd className="mt-0.5 font-medium text-slate-800">
                  Chunk #{currentSource.chunk_index}
                </dd>
              </div>
            </div>
          </div>

          {/* Supporting Passage Section */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
                Supporting Passage
              </h4>
              {evidence?.content && !loading && (
                <button
                  type="button"
                  onClick={handleCopyPassage}
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-600 hover:text-brand-700 cursor-pointer"
                  aria-label="Copy supporting passage to clipboard"
                >
                  {copied ? (
                    <span className="text-emerald-700 font-semibold" aria-live="polite">Copied!</span>
                  ) : (
                    <span>Copy passage</span>
                  )}
                </button>
              )}
            </div>

            {/* Truncation Notice if content exceeds max length */}
            {evidence?.is_truncated && !loading && !error && (
              <div className="flex items-center gap-2 rounded-lg border border-amber-200/90 bg-amber-50/80 p-2.5 text-xs text-amber-900">
                <svg className="h-4 w-4 shrink-0 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                <p className="text-[11px] leading-tight">
                  <span className="font-semibold">Shortened passage:</span> Showing the beginning of the supporting passage (maximum excerpt limit reached).
                </p>
              </div>
            )}

            {/* Loading State */}
            {loading && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-slate-500" role="status">
                <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-600 border-t-transparent mb-2" />
                <p className="text-xs">Loading supporting passage…</p>
              </div>
            )}

            {/* Error State */}
            {!loading && error && (
              <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800 space-y-2" role="alert">
                <p className="font-semibold">Unable to load source passage</p>
                <p className="text-[11px] text-rose-700 leading-normal">{error}</p>
                <Button variant="secondary" size="sm" onClick={handleRetry} className="mt-1 !border-rose-300 !text-rose-800 hover:!bg-rose-100/60">
                  Try again
                </Button>
              </div>
            )}

            {/* Loaded Evidence Text */}
            {!loading && !error && evidence && (
              <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs">
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-800 font-sans select-text">
                  {evidence.content}
                </p>
              </div>
            )}
          </div>

          {/* Provenance Grounding Context */}
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 text-[11px] text-slate-500 leading-normal">
            <span className="font-medium text-slate-700">Verified Evidence:</span> This passage was indexed from the original PDF and retrieved by vector search to ground the assistant response.
          </div>
        </div>

        {/* 4. Footer */}
        <div className="border-t border-slate-200 bg-slate-50/70 p-3 flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close inspector
          </Button>
        </div>
      </aside>
    </>
  );
}
