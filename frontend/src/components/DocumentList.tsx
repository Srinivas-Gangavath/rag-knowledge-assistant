import { useState, useMemo } from "react";

import { DocumentAclModal } from "./DocumentAclModal";
import { DocumentDetailsModal } from "./DocumentDetailsModal";
import { DocumentStatusBadge } from "./DocumentStatusBadge";
import { TrashIcon } from "./icons";
import type { DocumentRecord, DocumentStatus } from "../types";
import { formatDate, formatFileSize } from "../utils/format";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  Button,
  IconButton,
  Modal,
  EmptyState,
  Select,
} from "./ui";

type DocumentListProps = {
  documents: DocumentRecord[];
  deletingId: string | null;
  canDelete?: boolean;
  canManageAcl?: boolean;
  onDelete: (document: DocumentRecord) => Promise<void> | void;
};

type SortOption =
  | "updated_desc"
  | "created_desc"
  | "name_asc"
  | "name_desc"
  | "size_desc"
  | "size_asc";

export function DocumentList({
  documents,
  deletingId,
  canDelete = true,
  canManageAcl = true,
  onDelete,
}: DocumentListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | DocumentStatus>("ALL");
  const [sortBy, setSortBy] = useState<SortOption>("updated_desc");

  // Modals state
  const [pendingDelete, setPendingDelete] = useState<DocumentRecord | null>(null);
  const [aclDoc, setAclDoc] = useState<DocumentRecord | null>(null);
  const [detailsDoc, setDetailsDoc] = useState<DocumentRecord | null>(null);

  // Status counts
  const totalCount = documents.length;
  const readyCount = documents.filter((d) => d.status === "COMPLETED").length;
  const processingCount = documents.filter((d) => d.status === "PROCESSING").length;
  const failedCount = documents.filter((d) => d.status === "FAILED").length;

  // Filter and sort documents client-side
  const filteredAndSortedDocuments = useMemo(() => {
    let result = [...documents];

    // Status filter
    if (statusFilter !== "ALL") {
      result = result.filter((doc) => doc.status === statusFilter);
    }

    // Search query
    if (searchQuery.trim().length > 0) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (doc) =>
          doc.original_filename?.toLowerCase().includes(q) ||
          doc.filename?.toLowerCase().includes(q),
      );
    }

    // Sort
    result.sort((a, b) => {
      switch (sortBy) {
        case "created_desc":
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case "name_asc":
          return (a.original_filename || a.filename).localeCompare(
            b.original_filename || b.filename,
          );
        case "name_desc":
          return (b.original_filename || b.filename).localeCompare(
            a.original_filename || a.filename,
          );
        case "size_desc":
          return b.file_size - a.file_size;
        case "size_asc":
          return a.file_size - b.file_size;
        case "updated_desc":
        default:
          return (
            new Date(b.updated_at || b.created_at).getTime() -
            new Date(a.updated_at || a.created_at).getTime()
          );
      }
    });

    return result;
  }, [documents, statusFilter, searchQuery, sortBy]);

  const isFiltered = statusFilter !== "ALL" || searchQuery.trim().length > 0;

  function clearFilters() {
    setStatusFilter("ALL");
    setSearchQuery("");
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    await onDelete(target);
  }

  return (
    <div className="space-y-4">
      {/* 1. Knowledge Library Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Search Input */}
        <div className="relative flex-1 max-w-sm">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400">
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
                d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
              />
            </svg>
          </div>
          <input
            id="document-search-input"
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search documents…"
            aria-label="Search documents by filename"
            className="w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-9 pr-8 text-xs text-slate-900 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 shadow-xs"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery("")}
              className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-slate-400 hover:text-slate-600"
              aria-label="Clear search query"
            >
              ✕
            </button>
          )}
        </div>

        {/* Sort & Result Count */}
        <div className="flex items-center justify-between sm:justify-end gap-3">
          <div className="text-xs text-slate-500">
            {isFiltered ? (
              <span>
                <strong className="font-semibold text-slate-800">
                  {filteredAndSortedDocuments.length}
                </strong>{" "}
                of {totalCount} documents
              </span>
            ) : (
              <span>
                <strong className="font-semibold text-slate-800">{totalCount}</strong>{" "}
                {totalCount === 1 ? "document" : "documents"}
              </span>
            )}
          </div>

          <div className="w-44 shrink-0">
            <Select
              id="document-sort"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as SortOption)}
              aria-label="Sort documents"
              options={[
                { value: "updated_desc", label: "Recently updated" },
                { value: "created_desc", label: "Recently added" },
                { value: "name_asc", label: "Name A–Z" },
                { value: "name_desc", label: "Name Z–A" },
                { value: "size_desc", label: "Largest size" },
                { value: "size_asc", label: "Smallest size" },
              ]}
            />
          </div>
        </div>
      </div>

      {/* 2. Status Filter Segmented Strip */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-y border-slate-100 py-2.5">
        <div
          className="flex flex-wrap items-center gap-1.5"
          role="tablist"
          aria-label="Filter documents by status"
        >
          <button
            type="button"
            role="tab"
            aria-selected={statusFilter === "ALL"}
            onClick={() => setStatusFilter("ALL")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              statusFilter === "ALL"
                ? "bg-slate-900 text-white shadow-xs"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
            }`}
          >
            All <span className="opacity-75 ml-1">({totalCount})</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={statusFilter === "COMPLETED"}
            onClick={() => setStatusFilter("COMPLETED")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              statusFilter === "COMPLETED"
                ? "bg-emerald-700 text-white shadow-xs"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
            }`}
          >
            Ready <span className="opacity-75 ml-1">({readyCount})</span>
          </button>

          {processingCount > 0 && (
            <button
              type="button"
              role="tab"
              aria-selected={statusFilter === "PROCESSING"}
              onClick={() => setStatusFilter("PROCESSING")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                statusFilter === "PROCESSING"
                  ? "bg-amber-700 text-white shadow-xs"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
              }`}
            >
              Processing <span className="opacity-75 ml-1">({processingCount})</span>
            </button>
          )}

          <button
            type="button"
            role="tab"
            aria-selected={statusFilter === "FAILED"}
            onClick={() => setStatusFilter("FAILED")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              statusFilter === "FAILED"
                ? "bg-rose-700 text-white shadow-xs"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
            }`}
          >
            Failed <span className="opacity-75 ml-1">({failedCount})</span>
          </button>
        </div>

        {/* Clear Filters Button */}
        {isFiltered && (
          <button
            type="button"
            onClick={clearFilters}
            className="text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* 3. Search / Filter Empty State */}
      {filteredAndSortedDocuments.length === 0 ? (
        <EmptyState
          title="No matching documents"
          description="No knowledge sources match your current search or status filter."
          action={
            <Button variant="secondary" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          }
        />
      ) : (
        <>
          {/* 4. Desktop Table View */}
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <tr>
                  <TableHead>Document</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Pages</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead>Access</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </tr>
              </TableHeader>
              <TableBody>
                {filteredAndSortedDocuments.map((document) => (
                  <TableRow key={document.id}>
                    {/* Document Title & Icon */}
                    <TableCell className="max-w-xs">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                          <svg
                            className="h-3.5 w-3.5"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={1.75}
                            aria-hidden="true"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
                            />
                          </svg>
                        </span>
                        <div className="min-w-0">
                          <button
                            type="button"
                            onClick={() => setDetailsDoc(document)}
                            className="truncate text-left font-semibold text-slate-900 hover:text-brand-600 block transition-colors"
                            title={document.original_filename || document.filename}
                          >
                            {document.original_filename || document.filename}
                          </button>
                        </div>
                      </div>
                    </TableCell>

                    {/* Status */}
                    <TableCell>
                      <DocumentStatusBadge status={document.status} />
                    </TableCell>

                    {/* Pages */}
                    <TableCell className="text-slate-600">
                      {document.page_count != null ? document.page_count : "—"}
                    </TableCell>

                    {/* Size */}
                    <TableCell className="text-slate-600">
                      {formatFileSize(document.file_size)}
                    </TableCell>

                    {/* Updated */}
                    <TableCell className="text-slate-600">
                      {formatDate(document.updated_at || document.created_at)}
                    </TableCell>

                    {/* Access Action */}
                    <TableCell>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => setAclDoc(document)}
                      >
                        Manage access
                      </Button>
                    </TableCell>

                    {/* Action Menu / Delete */}
                    <TableCell className="text-right">
                      <div className="inline-flex items-center gap-1.5">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setDetailsDoc(document)}
                        >
                          Details
                        </Button>
                        {canDelete && (
                          <IconButton
                            variant="ghost"
                            size="sm"
                            aria-label={`Delete ${document.original_filename}`}
                            disabled={deletingId === document.id}
                            onClick={() => setPendingDelete(document)}
                            className="!text-slate-400 hover:!text-rose-600 hover:!bg-rose-50"
                          >
                            <TrashIcon className="h-4 w-4" />
                          </IconButton>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* 5. Mobile / Tablet Responsive Cards */}
          <ul className="space-y-3 md:hidden">
            {filteredAndSortedDocuments.map((document) => (
              <li
                key={document.id}
                className="rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-xs"
              >
                <div className="flex items-start justify-between gap-2.5">
                  <button
                    type="button"
                    onClick={() => setDetailsDoc(document)}
                    className="min-w-0 text-left font-semibold text-xs text-slate-900 truncate hover:text-brand-600"
                  >
                    {document.original_filename || document.filename}
                  </button>
                  <DocumentStatusBadge status={document.status} />
                </div>

                <dl className="mt-2.5 grid grid-cols-3 gap-2 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
                  <div>
                    <dt className="text-slate-400">Pages</dt>
                    <dd className="font-medium text-slate-700">
                      {document.page_count ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-400">Size</dt>
                    <dd className="font-medium text-slate-700">
                      {formatFileSize(document.file_size)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-400">Updated</dt>
                    <dd className="font-medium text-slate-700 truncate">
                      {formatDate(document.updated_at || document.created_at)}
                    </dd>
                  </div>
                </dl>

                <div className="mt-3 flex items-center justify-end gap-2 border-t border-slate-100 pt-2.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setDetailsDoc(document)}
                  >
                    Details
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => setAclDoc(document)}
                  >
                    Access
                  </Button>
                  {canDelete && (
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      disabled={deletingId === document.id}
                      onClick={() => setPendingDelete(document)}
                    >
                      Delete
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      {/* 6. Document Details Modal */}
      {detailsDoc && (
        <DocumentDetailsModal
          document={detailsDoc}
          onClose={() => setDetailsDoc(null)}
          onManageAccess={(doc) => setAclDoc(doc)}
          onDelete={(doc) => setPendingDelete(doc)}
          canManageAccess={canManageAcl}
          canDelete={canDelete}
        />
      )}

      {/* 7. Document ACL Modal */}
      {aclDoc && (
        <DocumentAclModal
          document={aclDoc}
          onClose={() => setAclDoc(null)}
        />
      )}

      {/* 8. Delete Confirmation Modal */}
      {pendingDelete && (
        <Modal
          isOpen={Boolean(pendingDelete)}
          onClose={() => setPendingDelete(null)}
          title={`Delete "${pendingDelete.original_filename || pendingDelete.filename}"?`}
          description="This will permanently remove the document from this workspace."
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
                Delete document
              </Button>
            </>
          }
        >
          <p className="text-xs text-slate-600">
            This action cannot be undone. All passage chunks and vector embeddings associated with this document will be permanently deleted.
          </p>
        </Modal>
      )}
    </div>
  );
}
