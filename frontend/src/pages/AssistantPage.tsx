import { useCallback, useEffect, useState } from "react";
import { ChatWindow } from "../components/chat/ChatWindow";
import { ConversationList } from "../components/chat/ConversationList";
import { api } from "../services/api";
import { userFacingError } from "../services/errors";
import type { AppView, ConversationSummary } from "../types";
import { PageShell, PageHeader } from "../components/layout";
import {
  Card,
  CardContent,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
} from "../components/ui";

type AssistantPageProps = {
  onNavigate: (view: AppView) => void;
};

export function AssistantPage({ onNavigate }: AssistantPageProps) {
  const [documentCount, setDocumentCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Mobile sidebar drawer state
  const [showMobileSidebar, setShowMobileSidebar] = useState(false);

  function loadDocuments() {
    setLoading(true);
    setError(null);
    api
      .listDocuments()
      .then((data) => {
        setDocumentCount(data.documents.length);
        setError(null);
      })
      .catch((err) => {
        setError(userFacingError(err, "list"));
      })
      .finally(() => {
        setLoading(false);
      });
  }

  const loadConversations = useCallback(async () => {
    setListError(null);
    const data = await api.listConversations();
    setConversations(data.conversations);
  }, []);

  useEffect(() => {
    loadDocuments();
  }, []);

  useEffect(() => {
    if (documentCount === null || documentCount === 0 || error) {
      return;
    }
    let cancelled = false;
    setListLoading(true);
    loadConversations()
      .catch((err) => {
        if (!cancelled) {
          setListError(userFacingError(err, "list"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setListLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [documentCount, error, loadConversations]);

  function handleNewConversation() {
    setConversationId(null);
    setShowMobileSidebar(false);
  }

  async function handleDelete(conversation: ConversationSummary) {
    setDeletingId(conversation.id);
    setListError(null);
    try {
      await api.deleteConversation(conversation.id);
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      if (conversationId === conversation.id) {
        setConversationId(null);
      }
    } catch (err) {
      setListError(userFacingError(err, "list"));
    } finally {
      setDeletingId(null);
    }
  }

  const chatReady = !loading && !error && documentCount !== null && documentCount > 0;

  return (
    <PageShell>
      {/* 1. Assistant Page Header */}
      <PageHeader
        title="Assistant"
        description="Ask questions about the knowledge available to your workspace."
        action={
          chatReady ? (
            <div className="flex items-center gap-2">
              {/* Mobile Sidebar Toggle */}
              <Button
                variant="secondary"
                size="sm"
                className="md:hidden"
                onClick={() => setShowMobileSidebar((prev) => !prev)}
                aria-label="Toggle conversations list"
              >
                <svg className="h-4 w-4 mr-1 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
                Chats {conversations.length > 0 && `(${conversations.length})`}
              </Button>

              <Button
                variant="primary"
                size="sm"
                onClick={handleNewConversation}
                startIcon={
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                }
              >
                New conversation
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* 2. Loading State */}
      {loading && (
        <Card>
          <CardContent>
            <LoadingState message="Checking knowledge base documents…" />
          </CardContent>
        </Card>
      )}

      {/* 3. Error State */}
      {!loading && error && (
        <ErrorState
          title="Unable to load knowledge base"
          message={error}
          onRetry={loadDocuments}
        />
      )}

      {/* 4. Empty Documents State */}
      {!loading && !error && documentCount === 0 && (
        <EmptyState
          title="No documents available yet"
          description="Upload a PDF to your workspace to start asking grounded questions."
          action={
            <Button
              variant="primary"
              size="sm"
              onClick={() => onNavigate("documents")}
            >
              Go to Documents
            </Button>
          }
        />
      )}

      {/* 5. Chat Interface Layout */}
      {chatReady && (
        <div className="relative grid gap-4 md:grid-cols-[17.5rem_minmax(0,1fr)] lg:grid-cols-[19rem_minmax(0,1fr)] items-start">
          {/* Desktop Conversation Sidebar */}
          <div className="hidden md:block h-[calc(100vh-14rem)] min-h-[34rem] sticky top-4">
            <ConversationList
              conversations={conversations}
              selectedId={conversationId}
              loading={listLoading}
              error={listError}
              deletingId={deletingId}
              onSelect={(id) => setConversationId(id)}
              onNew={handleNewConversation}
              onDelete={handleDelete}
              onRetry={() => {
                setListLoading(true);
                loadConversations()
                  .catch((err) => setListError(userFacingError(err, "list")))
                  .finally(() => setListLoading(false));
              }}
            />
          </div>

          {/* Mobile Overlay Sidebar Drawer */}
          {showMobileSidebar && (
            <div className="fixed inset-0 z-50 flex md:hidden">
              <div
                className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs transition-opacity"
                onClick={() => setShowMobileSidebar(false)}
                aria-hidden="true"
              />
              <div className="relative z-10 w-4/5 max-w-xs bg-white h-full p-3 shadow-xl flex flex-col">
                <div className="flex justify-end pb-2">
                  <button
                    type="button"
                    onClick={() => setShowMobileSidebar(false)}
                    className="p-1 rounded-lg text-slate-400 hover:text-slate-600"
                    aria-label="Close conversations menu"
                  >
                    ✕
                  </button>
                </div>
                <div className="flex-1 overflow-hidden">
                  <ConversationList
                    conversations={conversations}
                    selectedId={conversationId}
                    loading={listLoading}
                    error={listError}
                    deletingId={deletingId}
                    onSelect={(id) => {
                      setConversationId(id);
                      setShowMobileSidebar(false);
                    }}
                    onNew={handleNewConversation}
                    onDelete={handleDelete}
                    onRetry={() => {
                      setListLoading(true);
                      loadConversations()
                        .catch((err) => setListError(userFacingError(err, "list")))
                        .finally(() => setListLoading(false));
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Main Chat Workspace */}
          <div className="h-[calc(100vh-14rem)] min-h-[34rem] flex flex-col min-w-0">
            <ChatWindow
              conversationId={conversationId}
              onConversationChange={setConversationId}
              onHistoryMutated={() => {
                void loadConversations().catch((err) => {
                  setListError(userFacingError(err, "list"));
                });
              }}
            />
          </div>
        </div>
      )}
    </PageShell>
  );
}
