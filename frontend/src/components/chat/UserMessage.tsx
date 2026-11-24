type UserMessageProps = {
  content: string;
};

export function UserMessage({ content }: UserMessageProps) {
  return (
    <article className="flex justify-end" aria-label="Your question">
      <div className="max-w-[min(100%,36rem)] rounded-2xl rounded-tr-sm bg-slate-900 px-4 py-2.5 text-xs leading-relaxed text-white shadow-xs">
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
    </article>
  );
}
