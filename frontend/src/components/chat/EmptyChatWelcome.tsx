type EmptyChatWelcomeProps = {
  onSelectPrompt: (prompt: string) => void;
};

const SUGGESTED_PROMPTS = [
  "What are the main topics in my documents?",
  "Summarize the key information in this knowledge base.",
  "What should I know about the latest uploaded document?",
];

export function EmptyChatWelcome({ onSelectPrompt }: EmptyChatWelcomeProps) {
  return (
    <div className="my-auto flex flex-col items-center justify-center px-4 py-8 text-center">
      {/* Brand Icon Badge */}
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 border border-brand-200/80 text-brand-600 shadow-xs mb-3.5">
        <svg
          className="h-6 w-6"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.75}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z"
          />
        </svg>
      </div>

      <h2 className="text-base font-bold text-slate-900">Knowledge Assistant</h2>
      <p className="mt-1 max-w-sm text-xs text-slate-500">
        Ask questions about your workspace documents. Responses are grounded in indexed knowledge with verifiable source citations.
      </p>

      {/* Suggested prompts */}
      <div className="mt-6 w-full max-w-md space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Example Inquiries
        </p>
        <div className="grid gap-2">
          {SUGGESTED_PROMPTS.map((prompt, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => onSelectPrompt(prompt)}
              className="flex items-center justify-between rounded-xl border border-slate-200/90 bg-white p-3 text-left text-xs font-medium text-slate-700 shadow-xs hover:border-brand-300 hover:bg-brand-50/50 hover:text-brand-900 transition-all group"
            >
              <span>{prompt}</span>
              <span className="text-slate-400 group-hover:text-brand-600 transition-colors ml-2">
                →
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
