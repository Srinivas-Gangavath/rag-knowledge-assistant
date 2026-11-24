import type { ChatSource } from "../types";

type SourceListProps = {
  sources: ChatSource[];
};

export function SourceList({ sources }: SourceListProps) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <section className="mt-4" aria-labelledby="sources-heading">
      <h3 id="sources-heading" className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Sources
      </h3>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {sources.map((source) => (
          <li
            key={`${source.document_id}-${source.chunk_index}`}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2.5"
          >
            <p className="truncate text-sm font-medium text-slate-800">{source.filename}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              {source.page_number != null ? `Page ${source.page_number}` : "Page unknown"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
