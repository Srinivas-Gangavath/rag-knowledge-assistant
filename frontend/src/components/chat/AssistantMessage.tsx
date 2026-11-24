import { useState } from "react";
import type { ChatSource } from "../../types";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { StreamingIndicator } from "./StreamingIndicator";

type AssistantMessageProps = {
  content: string;
  sources: ChatSource[];
  pending?: boolean;
  onOpenSourceInspector: (sourceIndex: number) => void;
};

export function AssistantMessage({
  content,
  sources = [],
  pending = false,
  onOpenSourceInspector,
}: AssistantMessageProps) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    if (!content) return;
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const hasSources = sources.length > 0;

  return (
    <article className="flex justify-start" aria-label="Assistant answer">
      <div className="w-full max-w-3xl space-y-3 rounded-2xl rounded-tl-sm border border-slate-200/90 bg-white p-4 sm:p-5 shadow-xs">
        {/* Assistant Header & Actions */}
        <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-brand-50 text-brand-600 text-[10px] font-bold">
              AI
            </span>
            <span className="text-xs font-semibold text-slate-900">Knowledge Assistant</span>
          </div>

          <div className="flex items-center gap-2">
            {content && !pending && (
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition-colors"
                aria-label="Copy answer to clipboard"
              >
                {copied ? (
                  <>
                    <svg className="h-3.5 w-3.5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    <span className="text-emerald-700">Copied!</span>
                  </>
                ) : (
                  <>
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" />
                    </svg>
                    <span>Copy</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Message Content */}
        <div className="text-xs text-slate-800">
          {pending && !content ? (
            <StreamingIndicator />
          ) : (
            <MarkdownRenderer
              content={content}
              onCitationClick={(num) => onOpenSourceInspector(num - 1)}
              sourcesCount={sources.length}
            />
          )}
          {pending && content && (
            <div className="mt-2">
              <StreamingIndicator />
            </div>
          )}
        </div>

        {/* Grounding & Sources Section */}
        {!pending && (
          <div className="border-t border-slate-100 pt-3 space-y-2">
            {/* Grounding Pill */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[11px] font-medium">
                {hasSources ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-800 border border-emerald-200/60">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    Grounded in {sources.length} {sources.length === 1 ? "source" : "sources"}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 border border-slate-200/80">
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                    No supporting sources found
                  </span>
                )}
              </div>
            </div>

            {/* Source Reference Chips */}
            {hasSources && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                {sources.map((source, idx) => (
                  <button
                    key={`${source.document_id}-${source.chunk_index}-${idx}`}
                    type="button"
                    onClick={() => onOpenSourceInspector(idx)}
                    className="group inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/70 px-2.5 py-1 text-[11px] text-slate-700 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-900 transition-all focus:outline-none focus:ring-1 focus:ring-brand-500"
                    title={`Inspect ${source.filename} (${source.page_number != null ? `Page ${source.page_number}` : "Page unknown"})`}
                  >
                    <span className="font-semibold text-brand-700 group-hover:text-brand-900">
                      [{idx + 1}]
                    </span>
                    <span className="truncate max-w-[140px] sm:max-w-[200px] font-medium">
                      {source.filename}
                    </span>
                    {source.page_number != null && (
                      <span className="text-[10px] text-slate-400">
                        p.{source.page_number}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
