type PlaceholderPageProps = {
  title: string;
  summary: string;
};

export function PlaceholderPage({ title, summary }: PlaceholderPageProps) {
  return (
    <div className="mx-auto max-w-2xl">
      <section className="card">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">{summary}</p>
        <p className="mt-4 text-sm text-slate-500">
          This area is reserved for a later release.
        </p>
      </section>
    </div>
  );
}
