import { useCallback, useEffect, useState } from "react";

import { DocumentList } from "../components/DocumentList";
import { DocumentUpload } from "../components/DocumentUpload";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { userFacingError } from "../services/errors";
import type { DocumentRecord } from "../types";
import { PageShell, PageHeader } from "../components/layout";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  EmptyState,
  ErrorState,
  LoadingState,
} from "../components/ui";

export function DocumentsPage() {
  const { canUpload, canDelete, isWorkspaceAdmin, activeWorkspace } = useAuth();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    setListError(null);
    const data = await api.listDocuments();
    setDocuments(data.documents);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadDocuments()
      .catch((error) => {
        if (!cancelled) {
          setListError(userFacingError(error, "list"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadDocuments]);

  async function handleUploaded() {
    try {
      await loadDocuments();
    } catch (error) {
      setListError(userFacingError(error, "list"));
    }
  }

  async function handleRetry() {
    setLoading(true);
    try {
      await loadDocuments();
    } catch (error) {
      setListError(userFacingError(error, "list"));
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(document: DocumentRecord) {
    setDeletingId(document.id);
    setListError(null);
    try {
      await api.deleteDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
    } catch (error) {
      setListError(userFacingError(error, "list"));
    } finally {
      setDeletingId(null);
    }
  }

  function handleScrollToUpload() {
    const el = document.getElementById("document-upload-card");
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
    const input = document.getElementById("pdf-upload-input");
    if (input) {
      input.click();
    }
  }

  return (
    <PageShell>
      {/* 1. Page Header */}
      <PageHeader
        title="Documents"
        description="Upload and manage the knowledge base available to your workspace."
        action={
          canUpload ? (
            <Button
              variant="primary"
              size="sm"
              onClick={handleScrollToUpload}
              startIcon={
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 4.5v15m7.5-7.5h-15"
                  />
                </svg>
              }
            >
              Add documents
            </Button>
          ) : undefined
        }
      />

      {/* 2. Upload Section or Viewer Read-Only Notice */}
      {!canUpload ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-3.5 text-xs text-slate-600">
          You have read-only (Viewer) access to{" "}
          <span className="font-semibold text-slate-800">
            {activeWorkspace?.name || "this workspace"}
          </span>
          . Uploading new documents is restricted to Contributors and Admins.
        </div>
      ) : (
        <DocumentUpload
          uploading={uploading}
          onUploadingChange={setUploading}
          onUploaded={handleUploaded}
        />
      )}

      {/* 3. Knowledge Library Card */}
      <Card aria-labelledby="document-library-heading" aria-busy={loading || uploading}>
        <CardHeader className="border-b border-slate-100 pb-3">
          <div>
            <CardTitle id="document-library-heading">Knowledge Library</CardTitle>
            <CardDescription>
              All indexed knowledge sources available for retrieval in this workspace
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="pt-4">
          {loading ? (
            <LoadingState message="Loading document library…" />
          ) : null}

          {!loading && listError ? (
            <ErrorState
              title="Unable to load documents"
              message={listError}
              onRetry={handleRetry}
            />
          ) : null}

          {!loading && !listError && documents.length === 0 ? (
            <EmptyState
              title="Your knowledge base is empty"
              description={
                canUpload
                  ? "Add your first document to make it available to the assistant for grounded answering."
                  : "No documents have been uploaded to this workspace yet."
              }
              action={
                canUpload ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleScrollToUpload}
                  >
                    Add documents
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !listError && documents.length > 0 ? (
            <DocumentList
              documents={documents}
              deletingId={deletingId}
              onDelete={handleDelete}
              canDelete={canDelete}
              canManageAcl={isWorkspaceAdmin}
            />
          ) : null}
        </CardContent>
      </Card>
    </PageShell>
  );
}
