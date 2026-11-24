import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Button } from "../ui";

type ChatComposerProps = {
  value: string;
  onChange: (val: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  loading: boolean;
  disabled?: boolean;
  error?: string | null;
};

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  loading,
  disabled = false,
  error = null,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea height based on content
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!loading && !disabled && value.trim()) {
        onSubmit();
      }
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!loading && !disabled && value.trim()) {
      onSubmit();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative rounded-2xl border border-slate-200/90 bg-white p-3 shadow-sm focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500 transition-all">
      <textarea
        id="chat-composer-textarea"
        ref={textareaRef}
        rows={1}
        value={value}
        disabled={disabled}
        placeholder="Ask a question about your knowledge…"
        aria-label="Ask a question about your knowledge base"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        className="w-full resize-none border-0 bg-transparent p-1.5 text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-0 max-h-44 leading-relaxed"
      />

      <div className="flex items-center justify-between border-t border-slate-100 pt-2.5 mt-1">
        <div className="text-[11px] text-slate-400">
          {loading ? (
            <span className="text-amber-700 font-medium">Generating answer…</span>
          ) : (
            <span>Press <kbd className="font-mono rounded bg-slate-100 px-1 py-0.5 text-slate-600 text-[10px]">Enter</kbd> to send • <kbd className="font-mono rounded bg-slate-100 px-1 py-0.5 text-slate-600 text-[10px]">Shift+Enter</kbd> for newline</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {loading ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onStop}
              className="!border-slate-300 !text-slate-700 hover:!bg-slate-100 font-medium"
            >
              <svg className="h-3.5 w-3.5 mr-1 text-slate-500" fill="currentColor" viewBox="0 0 24 24">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              Stop
            </Button>
          ) : (
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={disabled || !value.trim()}
              className="px-3.5"
            >
              Send
              <svg className="h-3.5 w-3.5 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            </Button>
          )}
        </div>
      </div>

      {error && (
        <p className="mt-2 text-xs text-rose-700" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
