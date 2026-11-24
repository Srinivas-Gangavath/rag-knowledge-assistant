import { useState, useMemo } from "react";
import { TrashIcon } from "../icons";
import type { ConversationSummary } from "../../types";
import { formatDate } from "../../utils/format";
import { Button, IconButton, Modal } from "../ui";

type ConversationListProps = {
  conversations: ConversationSummary[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  deletingId: string | null;
  onSelect: (conversationId: string) => void;
  onNew: () => void;
  onDelete: (conversation: ConversationSummary) => Promise<void> | void;
  onRetry: () => void;
};

export function ConversationList({
  conversations,
  selectedId,
  loading,
  error,
  deletingId,
  onSelect,
  onNew,
  onDelete,
  onRetry,
}: ConversationListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ConversationSummary | null>(null);

  // Client-side search filter by title
  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const q = searchQuery.toLowerCase().trim();
    return conversations.filter((c) =>
      (c.title || "New conversation").toLowerCase().includes(q)
    );
  }, [conversations, searchQuery]);

  async function confirmDelete() {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    await onDelete(target);
  }

  return (
    <nav
      className="flex h-full min-h-[30rem] flex-col rounded-2xl border border-slate-200/90 bg-white p-3.5 shadow-xs"
      aria-label="Conversations"
    >
      {/* 1. Header Toolbar */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b border-slate-100">
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
          Conversations
        </h3>
        <Button
          id="new-conversation-btn"
          variant="secondary"
          size="sm"
          onClick={onNew}
          className="!text-xs font-semibold"
          aria-label="Start a new conversation"
        >
          + New chat
        </Button>
      </div>

      {/* 2. Search Box */}
      {conversations.length > 0 && (
        <div className="relative mt-2.5 mb-2">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5 text-slate-400">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
          </div>
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations…"
            aria-label="Search conversations by title"
            className="w-full rounded-lg border border-slate-200 bg-slate-50/50 py-1.5 pl-8 pr-7 text-xs text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-brand-500 transition-colors"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute inset-y-0 right-0 flex items-center pr-2 text-slate-400 hover:text-slate-600"
              aria-label="Clear conversation search"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* 3. Loading State */}
      {loading && (
        <div className="my-auto py-8 text-center text-xs text-slate-400" role="status">
          <p>Loading conversations…</p>
        </div>
      )}

      {/* 4. Error State */}
      {!loading && error && (
        <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/80 p-3 text-xs" role="alert">
          <p className="text-rose-800">{error}</p>
          <Button variant="secondary" size="sm" className="mt-2 w-full" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}

      {/* 5. Empty Conversations State */}
      {!loading && !error && conversations.length === 0 && (
        <div className="my-auto py-8 text-center">
          <p className="text-xs font-medium text-slate-700">No conversations yet</p>
          <p className="mt-1 text-[11px] text-slate-400 leading-normal">
            Start a conversation to explore your knowledge base.
          </p>
          <Button variant="primary" size="sm" className="mt-3" onClick={onNew}>
            + New conversation
          </Button>
        </div>
      )}

      {/* 6. Filter Empty State */}
      {!loading && !error && conversations.length > 0 && filteredConversations.length === 0 && (
        <div className="my-auto py-6 text-center">
          <p className="text-xs text-slate-500">No conversations match &ldquo;{searchQuery}&rdquo;</p>
          <button
            type="button"
            onClick={() => setSearchQuery("")}
            className="mt-2 text-xs font-medium text-brand-600 hover:underline"
          >
            Clear search
          </button>
        </div>
      )}

      {/* 7. Conversations List */}
      {!loading && !error && filteredConversations.length > 0 && (
        <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-0.5">
          {filteredConversations.map((conversation) => {
            const isSelected = conversation.id === selectedId;
            const title = conversation.title?.trim() || "New conversation";

            return (
              <li key={conversation.id}>
                <div
                  className={[
                    "group flex items-center justify-between rounded-xl px-3 py-2 text-xs transition-all",
                    isSelected
                      ? "bg-brand-50/90 text-brand-950 font-semibold border border-brand-200/70 shadow-2xs"
                      : "text-slate-700 hover:bg-slate-100/70 border border-transparent",
                  ].join(" ")}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(conversation.id)}
                    aria-current={isSelected ? "true" : undefined}
                    className="min-w-0 flex-1 text-left focus:outline-none"
                  >
                    <span className="block truncate text-xs">
                      {title}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-slate-400 font-normal">
                      {formatDate(conversation.updated_at)}
                    </span>
                  </button>

                  <IconButton
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete ${title}`}
                    disabled={deletingId === conversation.id}
                    onClick={() => setPendingDelete(conversation)}
                    className="opacity-0 group-hover:opacity-100 !text-slate-400 hover:!text-rose-600 hover:!bg-rose-50 transition-opacity ml-1.5 shrink-0"
                  >
                    <TrashIcon className="h-3.5 w-3.5" />
                  </IconButton>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* 8. Delete Confirmation Modal */}
      {pendingDelete && (
        <Modal
          isOpen={Boolean(pendingDelete)}
          onClose={() => setPendingDelete(null)}
          title="Delete this conversation?"
          description="This conversation will be permanently removed."
          size="sm"
          footer={
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPendingDelete(null)}
              >
                Cancel
              </Button>
              <Button
                variant="danger-solid"
                size="sm"
                onClick={() => void confirmDelete()}
              >
                Delete conversation
              </Button>
            </>
          }
        >
          <p className="text-xs text-slate-600">
            This action cannot be undone. All messages and retrieved citations in &ldquo;{pendingDelete.title?.trim() || "New conversation"}&rdquo; will be permanently deleted.
          </p>
        </Modal>
      )}
    </nav>
  );
}
