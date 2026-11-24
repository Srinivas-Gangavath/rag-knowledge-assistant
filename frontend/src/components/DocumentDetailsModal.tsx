import { useEffect, useState } from "react";
import type { DocumentAcl, DocumentRecord } from "../types";
import { api } from "../services/api";
import { formatDate, formatFileSize } from "../utils/format";
import { DocumentStatusBadge } from "./DocumentStatusBadge";
import { Modal, Button } from "./ui";

type DocumentDetailsModalProps = {
  document: DocumentRecord | null;
  onClose: () => void;
  onManageAccess?: (document: DocumentRecord) => void;
  onDelete?: (document: DocumentRecord) => void;
  canManageAccess?: boolean;
  canDelete?: boolean;
};

export function DocumentDetailsModal({
  document,
  onClose,
  onManageAccess,
  onDelete,
  canManageAccess = false,
  canDelete = false,
}: DocumentDetailsModalProps) {
  const [acls, setAcls] = useState<DocumentAcl[] | null>(null);
  const [loadingAcls, setLoadingAcls] = useState(false);

  useEffect(() => {
    if (!document) {
      setAcls(null);
      return;
    }

    let cancelled = false;
    setLoadingAcls(true);

    api
      .listDocumentAcls(document.id)
      .then((res) => {
        if (!cancelled) setAcls(res.acls);
      })
      .catch(() => {
        if (!cancelled) setAcls([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingAcls(false);
      });

    return () => {
      cancelled = true;
    };
  }, [document]);

  if (!document) return null;

  const isCompleted = document.status === "COMPLETED";
  const isProcessing = document.status === "PROCESSING";
  const isFailed = document.status === "FAILED";

  return (
    <Modal
      isOpen={Boolean(document)}
      onClose={onClose}
      title="Document Details"
      description={document.original_filename || document.filename}
      size="md"
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2 w-full">
          <div className="flex items-center gap-2">
            {canDelete && onDelete && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => {
                  onClose();
                  onDelete(document);
                }}
              >
                Delete document
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {canManageAccess && onManageAccess && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  onClose();
                  onManageAccess(document);
                }}
              >
                Manage access
              </Button>
            )}
            <Button variant="primary" size="sm" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-4 text-xs">
        {/* 1. Overview & File Specifications */}
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Overview
            </h4>
            <DocumentStatusBadge status={document.status} />
          </div>

          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
            <div>
              <dt className="text-slate-500">Document Name</dt>
              <dd className="font-semibold text-slate-900 truncate" title={document.original_filename}>
                {document.original_filename || document.filename}
              </dd>
            </div>

            <div>
              <dt className="text-slate-500">File Size</dt>
              <dd className="font-medium text-slate-800">
                {formatFileSize(document.file_size)}
              </dd>
            </div>

            <div>
              <dt className="text-slate-500">Page Count</dt>
              <dd className="font-medium text-slate-800">
                {document.page_count != null ? `${document.page_count} pages` : "—"}
              </dd>
            </div>

            <div>
              <dt className="text-slate-500">Format</dt>
              <dd className="font-medium text-slate-800 uppercase">
                {document.file_type || "PDF"}
              </dd>
            </div>

            <div>
              <dt className="text-slate-500">Uploaded</dt>
              <dd className="font-medium text-slate-800">
                {formatDate(document.created_at)}
              </dd>
            </div>

            <div>
              <dt className="text-slate-500">Last Modified</dt>
              <dd className="font-medium text-slate-800">
                {formatDate(document.updated_at || document.created_at)}
              </dd>
            </div>
          </dl>
        </div>

        {/* 2. Processing Lifecycle Information */}
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
            Processing Lifecycle
          </h4>

          {isCompleted && (
            <div className="space-y-1">
              <p className="font-semibold text-emerald-800 flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
                Ready for retrieval
              </p>
              <p className="text-slate-600 leading-normal">
                This document is available to the assistant for grounded knowledge answers with verifiable citations.
              </p>
            </div>
          )}

          {isProcessing && (
            <div className="space-y-1">
              <p className="font-semibold text-amber-800 flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" aria-hidden="true" />
                Processing in progress
              </p>
              <p className="text-slate-600 leading-normal">
                Your document is being prepared for knowledge retrieval. Text extraction and semantic indexing are currently active.
              </p>
            </div>
          )}

          {isFailed && (
            <div className="space-y-2 rounded-lg border border-rose-200 bg-rose-50/80 p-3 text-rose-900">
              <div>
                <p className="font-semibold flex items-center gap-1.5 text-rose-800">
                  <span className="h-2 w-2 rounded-full bg-rose-500" aria-hidden="true" />
                  Processing failed
                </p>
                <p className="mt-0.5 text-[11px] text-rose-700 leading-normal">
                  The document could not be prepared for knowledge retrieval.
                </p>
              </div>

              <div className="border-t border-rose-200/60 pt-2 text-[11px]">
                <p className="font-medium text-rose-800">Recommended Next Step:</p>
                <p className="text-rose-700">
                  Ensure the PDF contains selectable text (not scanned images only) and is not password-protected. Delete this entry and upload a valid PDF.
                </p>
              </div>
            </div>
          )}

          {!isCompleted && !isProcessing && !isFailed && (
            <div className="space-y-1">
              <p className="font-semibold text-slate-700">Uploaded</p>
              <p className="text-slate-600 leading-normal">
                The document is saved in storage and awaiting processing.
              </p>
            </div>
          )}
        </div>

        {/* 3. Access Control Summary */}
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Access & Permissions
            </h4>
            {canManageAccess && onManageAccess && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onManageAccess(document);
                }}
                className="text-[11px] font-medium text-brand-600 hover:text-brand-700 hover:underline"
              >
                Manage access →
              </button>
            )}
          </div>

          {loadingAcls ? (
            <p className="text-slate-400">Loading access permissions…</p>
          ) : !acls || acls.length === 0 ? (
            <div className="text-slate-600 space-y-0.5">
              <p className="font-medium text-slate-800">Workspace Access (Default)</p>
              <p className="text-[11px] text-slate-500 leading-normal">
                Inherited from workspace permissions. All workspace members can access this document according to their role.
              </p>
            </div>
          ) : (
            <div className="text-slate-600 space-y-0.5">
              <p className="font-medium text-slate-800">Restricted Access</p>
              <p className="text-[11px] text-slate-500 leading-normal">
                {acls.length} explicit permission {acls.length === 1 ? "rule" : "rules"} defined for this document.
              </p>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
