import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "../../services/api";
import { StreamAbortedError, userFacingError } from "../../services/errors";
import type { ChatSource, ConversationMessage } from "../../types";
import { UserMessage } from "./UserMessage";
import { AssistantMessage } from "./AssistantMessage";
import { ChatComposer } from "./ChatComposer";
import { EmptyChatWelcome } from "./EmptyChatWelcome";
import { SourceDrawer } from "./SourceDrawer";
import { Button } from "../ui";

type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  error: string | null;
  pending: boolean;
};

type ChatWindowProps = {
  conversationId: string | null;
  onConversationChange: (conversationId: string) => void;
  onHistoryMutated: () => void;
};

function lastIndexOfRole(messages: DisplayMessage[], role: "user" | "assistant"): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === role) {
      return index;
    }
  }
  return -1;
}

function fromApiMessages(messages: ConversationMessage[]): DisplayMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    sources: message.sources ?? [],
    error: null,
    pending: false,
  }));
}

export function ChatWindow({
  conversationId,
  onConversationChange,
  onHistoryMutated,
}: ChatWindowProps) {
  const inFlightRef = useRef(false);
  const loadedConversationRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);

  // Auto-scroll tracking
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [showScrollBottom, setShowScrollBottom] = useState(false);

  // Source Inspector Drawer state
  const [activeInspectorSources, setActiveInspectorSources] = useState<ChatSource[]>([]);
  const [activeSourceIndex, setActiveSourceIndex] = useState<number | null>(null);
  const [isInspectorOpen, setIsInspectorOpen] = useState(false);

  const handleScroll = useCallback(() => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    const distanceToBottom = scrollHeight - (scrollTop + clientHeight);
    const atBottom = distanceToBottom < 100;
    setIsAtBottom(atBottom);
    setShowScrollBottom(!atBottom && messages.length > 0);
  }, [messages.length]);

  const scrollToBottom = useCallback((smooth = true) => {
    if (!scrollContainerRef.current) return;
    scrollContainerRef.current.scrollTo({
      top: scrollContainerRef.current.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  // Fetch conversation messages on selection
  useEffect(() => {
    if (!conversationId) {
      loadedConversationRef.current = null;
      setMessages([]);
      setHistoryError(null);
      setHistoryLoading(false);
      return;
    }

    if (loadedConversationRef.current === conversationId) {
      return;
    }

    let cancelled = false;
    setMessages([]);
    setHistoryLoading(true);
    setHistoryError(null);

    api
      .getConversation(conversationId)
      .then((detail) => {
        if (!cancelled) {
          loadedConversationRef.current = conversationId;
          setMessages(fromApiMessages(detail.messages));
          setTimeout(() => scrollToBottom(false), 50);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setHistoryError(userFacingError(error, "list"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setHistoryLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [conversationId, scrollToBottom]);

  // Handle auto-scrolling during streaming
  useEffect(() => {
    if (isAtBottom) {
      scrollToBottom(false);
    }
  }, [messages, isAtBottom, scrollToBottom]);

  function openSourceInspector(sources: ChatSource[], sourceIndex: number) {
    setActiveInspectorSources(sources);
    setActiveSourceIndex(sourceIndex);
    setIsInspectorOpen(true);
  }

  async function sendQuestion(raw: string, retry = false) {
    const trimmed = raw.trim();
    if (!trimmed) {
      setInputError("Please enter a question.");
      return;
    }
    if (inFlightRef.current) {
      return;
    }

    setInputError(null);
    inFlightRef.current = true;
    setLoading(true);
    const abort = new AbortController();
    abortRef.current = abort;

    const assistantId = `local-assistant-${Date.now()}`;
    if (retry) {
      setMessages((current) => {
        const withoutFailed = current.filter(
          (item) => !(item.role === "assistant" && item.error)
        );
        return [
          ...withoutFailed,
          {
            id: assistantId,
            role: "assistant",
            content: "",
            sources: [],
            error: null,
            pending: true,
          },
        ];
      });
    } else {
      setQuestion("");
      setMessages((current) => [
        ...current,
        {
          id: `local-user-${Date.now()}`,
          role: "user",
          content: trimmed,
          sources: [],
          error: null,
          pending: true,
        },
        {
          id: assistantId,
          role: "assistant",
          content: "",
          sources: [],
          error: null,
          pending: true,
        },
      ]);
    }

    setTimeout(() => scrollToBottom(true), 50);

    try {
      await api.chatStream(
        trimmed,
        conversationId,
        {
          onStart: (data) => {
            setMessages((current) => {
              const next = [...current];
              const userIndex = lastIndexOfRole(next, "user");
              if (userIndex >= 0) {
                next[userIndex] = {
                  ...next[userIndex],
                  id: data.user_message_id,
                  pending: false,
                };
              }
              return next;
            });
          },
          onToken: (text) => {
            setMessages((current) => {
              const next = [...current];
              const assistantIndex = lastIndexOfRole(next, "assistant");
              if (assistantIndex >= 0) {
                next[assistantIndex] = {
                  ...next[assistantIndex],
                  content: next[assistantIndex].content + text,
                  pending: true,
                  error: null,
                };
              }
              return next;
            });
          },
          onSources: (sources) => {
            setMessages((current) => {
              const next = [...current];
              const assistantIndex = lastIndexOfRole(next, "assistant");
              if (assistantIndex >= 0) {
                next[assistantIndex] = { ...next[assistantIndex], sources };
              }
              return next;
            });
          },
          onDone: (data) => {
            loadedConversationRef.current = data.conversation_id;
            setMessages((current) => {
              const next = [...current];
              const assistantIndex = lastIndexOfRole(next, "assistant");
              if (assistantIndex >= 0) {
                next[assistantIndex] = {
                  ...next[assistantIndex],
                  id: data.message_id,
                  pending: false,
                  error: null,
                };
              }
              return next;
            });
            if (data.conversation_id !== conversationId) {
              onConversationChange(data.conversation_id);
            }
            onHistoryMutated();
          },
        },
        abort.signal
      );
    } catch (error) {
      const cancelled = error instanceof StreamAbortedError;
      setMessages((current) => {
        const next = [...current];
        const assistantIndex = lastIndexOfRole(next, "assistant");
        if (assistantIndex >= 0) {
          next[assistantIndex] = {
            ...next[assistantIndex],
            pending: false,
            error: cancelled ? "Generation stopped." : userFacingError(error, "chat"),
          };
        }
        return next;
      });
    } finally {
      inFlightRef.current = false;
      abortRef.current = null;
      setLoading(false);
    }
  }

  function stopGeneration() {
    abortRef.current?.abort();
  }

  const lastMessage = messages[messages.length - 1];
  const lastUser = [...messages].reverse().find((item) => item.role === "user");
  const canRetry = Boolean(lastMessage?.error) && !loading;

  return (
    <div className="relative flex h-full min-h-[34rem] flex-col rounded-2xl border border-slate-200/90 bg-slate-50/40 shadow-xs overflow-hidden">
      {/* Messages Scroll Area */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 space-y-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation messages"
      >
        {historyLoading && (
          <div className="my-auto py-12 text-center text-xs text-slate-400" role="status">
            <p>Loading conversation history…</p>
          </div>
        )}

        {!historyLoading && historyError && (
          <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-4 text-xs text-rose-800" role="alert">
            <p className="font-semibold">Unable to load conversation</p>
            <p className="mt-1">{historyError}</p>
          </div>
        )}

        {!historyLoading && !historyError && messages.length === 0 && !loading && (
          <EmptyChatWelcome onSelectPrompt={(p) => void sendQuestion(p)} />
        )}

        {!historyError &&
          messages.map((message) => (
            <div key={message.id} className="space-y-2">
              {message.role === "user" ? (
                <UserMessage content={message.content} />
              ) : (
                <AssistantMessage
                  content={message.content}
                  sources={message.sources}
                  pending={message.pending}
                  onOpenSourceInspector={(srcIdx) => openSourceInspector(message.sources, srcIdx)}
                />
              )}

              {/* Turn Error & Retry */}
              {message.error && (
                <div className="rounded-xl border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-800 flex items-center justify-between" role="alert">
                  <div>
                    <p className="font-medium">{message.error}</p>
                  </div>
                  {canRetry && lastUser && message.id === lastMessage?.id && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => void sendQuestion(lastUser.content, true)}
                      className="!border-rose-300 !text-rose-800 hover:!bg-rose-100/60"
                    >
                      Try again
                    </Button>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>

      {/* Floating Jump to Latest Button */}
      {showScrollBottom && (
        <button
          type="button"
          onClick={() => scrollToBottom(true)}
          className="absolute bottom-28 right-6 z-20 inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white shadow-lg hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500 transition-all animate-bounce"
          aria-label="Jump to latest message"
        >
          <span>Jump to latest</span>
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 13.5L12 21m0 0l-7.5-7.5M12 21V3" />
          </svg>
        </button>
      )}

      {/* Composer Bottom Area */}
      <div className="border-t border-slate-200/80 bg-white p-3.5 sm:px-6 sm:py-4">
        <ChatComposer
          value={question}
          onChange={(val) => {
            setQuestion(val);
            if (inputError) setInputError(null);
          }}
          onSubmit={() => void sendQuestion(question)}
          onStop={stopGeneration}
          loading={loading}
          disabled={historyLoading}
          error={inputError}
        />
      </div>

      {/* Source Inspector Drawer */}
      <SourceDrawer
        isOpen={isInspectorOpen}
        onClose={() => setIsInspectorOpen(false)}
        sources={activeInspectorSources}
        activeSourceIndex={activeSourceIndex}
        onSelectSource={(idx) => setActiveSourceIndex(idx)}
      />
    </div>
  );
}
