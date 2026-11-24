export function StreamingIndicator() {
  return (
    <div
      className="inline-flex items-center gap-1.5 rounded-full bg-brand-50/80 px-2.5 py-1 text-[11px] font-medium text-brand-700 border border-brand-200/60"
      role="status"
      aria-label="Generating response"
    >
      <span className="flex h-1.5 w-1.5 relative">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-brand-600" />
      </span>
      <span>Generating response…</span>
    </div>
  );
}
