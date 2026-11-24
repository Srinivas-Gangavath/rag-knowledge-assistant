import { SourceList } from "./SourceList";
import type { ChatSource } from "../types";

type ChatMessageProps = {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
};

export function ChatMessage({ role, content, sources = [] }: ChatMessageProps) {
  const isUser = role === "user";

  return (
    <article
      className={isUser ? "flex justify-end" : "flex justify-start"}
      aria-label={isUser ? "Your question" : "Assistant answer"}
    >
      <div
        className={[
          "max-w-[min(100%,40rem)] rounded-xl px-4 py-3",
          isUser
            ? "bg-brand-600 text-white"
            : "border border-slate-200 bg-white text-slate-800 shadow-card",
        ].join(" ")}
      >
        <p className="whitespace-pre-wrap text-sm leading-6">{content}</p>
        {!isUser ? <SourceList sources={sources} /> : null}
      </div>
    </article>
  );
}
