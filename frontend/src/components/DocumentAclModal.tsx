import { useEffect, useState } from "react";

import { api } from "../services/api";
import { userFacingError } from "../services/errors";
import type { DocumentAcl, DocumentRecord } from "../types";
import { formatRole } from "../utils/format";
import {
  Modal,
  Button,
  Input,
  Select,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
  Badge,
  Toast,
} from "./ui";

type DocumentAclModalProps = {
  document: DocumentRecord | null;
  onClose: () => void;
};

export function DocumentAclModal({ document, onClose }: DocumentAclModalProps) {
  const [acls, setAcls] = useState<DocumentAcl[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [principalType, setPrincipalType] = useState<"USER" | "WORKSPACE_ROLE">("USER");
  const [principalId, setPrincipalId] = useState("");
  const [permission, setPermission] = useState<"READ" | "WRITE" | "ADMIN">("READ");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!document) return;
    let cancelled = false;

    async function loadAcls() {
      setLoading(true);
      setError(null);
      try {
        const res = await api.listDocumentAcls(document!.id);
        if (!cancelled) setAcls(res.acls);
      } catch (err) {
        if (!cancelled) setError(userFacingError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadAcls();
    return () => {
      cancelled = true;
    };
  }, [document]);

  if (!document) return null;

  async function handleAddAcl(e: React.FormEvent) {
    e.preventDefault();
    if (!principalId.trim()) return;
    setError(null);
    setSuccess(null);
    setSubmitting(true);

    try {
      const added = await api.addDocumentAcl(document!.id, {
        principal_type: principalType,
        principal_id: principalId.trim(),
        permission,
      });
      setAcls((prev) => [...prev, added]);
      setPrincipalId("");
      setSuccess("Access permission granted.");
    } catch (err) {
      setError(userFacingError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteAcl(aclId: string) {
    setError(null);
    setSuccess(null);
    try {
      await api.deleteDocumentAcl(document!.id, aclId);
      setAcls((prev) => prev.filter((a) => a.id !== aclId));
      setSuccess("Access permission removed.");
    } catch (err) {
      setError(userFacingError(err));
    }
  }

  return (
    <Modal
      isOpen={Boolean(document)}
      onClose={onClose}
      title="Document Access Control"
      description={document.original_filename}
      size="lg"
      footer={
        <Button variant="secondary" size="sm" onClick={onClose}>
          Done
        </Button>
      }
    >
      <div className="space-y-4">
        {/* Status banner */}
        {acls.length === 0 ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-3 text-xs text-emerald-800">
            <span className="font-semibold">Workspace Default Access:</span> All members in this workspace can access this document according to their workspace role.
          </div>
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-3 text-xs text-amber-800">
            <span className="font-semibold">Restricted Access:</span> Only the specific users and roles listed below can view or retrieve from this document.
          </div>
        )}

        {error && (
          <Toast type="error" message={error} onClose={() => setError(null)} />
        )}
        {success && (
          <Toast type="success" message={success} onClose={() => setSuccess(null)} />
        )}

        {/* Add Permission Form */}
        <form onSubmit={handleAddAcl} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
            Add Access Permission
          </h4>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Select
              id="principal-type"
              label="Principal Type"
              value={principalType}
              onChange={(e) => {
                const val = e.target.value as "USER" | "WORKSPACE_ROLE";
                setPrincipalType(val);
                setPrincipalId(val === "WORKSPACE_ROLE" ? "VIEWER" : "");
              }}
              options={[
                { value: "USER", label: "Specific User" },
                { value: "WORKSPACE_ROLE", label: "Workspace Role" },
              ]}
            />

            {principalType === "USER" ? (
              <Input
                id="principal-id"
                label="User Email or ID"
                type="text"
                required
                placeholder="name@company.com"
                value={principalId}
                onChange={(e) => setPrincipalId(e.target.value)}
              />
            ) : (
              <Select
                id="principal-id"
                label="Role"
                value={principalId}
                onChange={(e) => setPrincipalId(e.target.value)}
                options={[
                  { value: "VIEWER", label: "Viewer" },
                  { value: "CONTRIBUTOR", label: "Contributor" },
                  { value: "WORKSPACE_ADMIN", label: "Workspace Admin" },
                ]}
              />
            )}

            <Select
              id="permission-level"
              label="Permission"
              value={permission}
              onChange={(e) => setPermission(e.target.value as "READ" | "WRITE" | "ADMIN")}
              options={[
                { value: "READ", label: "READ (View & Search)" },
                { value: "WRITE", label: "WRITE (Edit Metadata)" },
                { value: "ADMIN", label: "ADMIN (Full Control)" },
              ]}
            />
          </div>

          <div className="mt-3.5 flex justify-end">
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={submitting}
              disabled={principalType === "USER" && !principalId.trim()}
            >
              + Grant Access
            </Button>
          </div>
        </form>

        {/* Current ACL Entries Table */}
        <div className="mt-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
            Current Access List
          </h4>
          {loading ? (
            <p className="py-4 text-center text-xs text-slate-500">Loading permissions…</p>
          ) : (
            <Table>
              <TableHeader>
                <tr>
                  <TableHead>Principal</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Permission</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </tr>
              </TableHeader>
              <TableBody>
                {acls.map((acl) => (
                  <TableRow key={acl.id}>
                    <TableCell className="font-semibold text-slate-800">
                      {acl.principal_type === "WORKSPACE_ROLE"
                        ? formatRole(acl.principal_id)
                        : acl.principal_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="neutral" size="sm">
                        {acl.principal_type === "WORKSPACE_ROLE" ? "Workspace Role" : "User"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="brand" size="sm">
                        {acl.permission === "READ"
                          ? "Read"
                          : acl.permission === "WRITE"
                            ? "Write"
                            : "Admin"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteAcl(acl.id)}
                        className="!text-rose-600 hover:!bg-rose-50"
                      >
                        Remove
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {acls.length === 0 && (
                  <TableEmpty
                    colSpan={4}
                    message="No custom ACL restrictions. All workspace members have default access."
                  />
                )}
              </TableBody>
            </Table>
          )}
        </div>
      </div>
    </Modal>
  );
}
