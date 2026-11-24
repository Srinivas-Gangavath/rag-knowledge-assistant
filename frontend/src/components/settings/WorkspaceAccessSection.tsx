import type { UserWorkspace } from "../../types";
import { formatRole } from "../../utils/format";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, Button, Badge } from "../ui";

type WorkspaceAccessSectionProps = {
  activeWorkspace: UserWorkspace | null;
  onNavigateToDocuments?: () => void;
};

export function WorkspaceAccessSection({
  activeWorkspace,
  onNavigateToDocuments,
}: WorkspaceAccessSectionProps) {
  const currentRole = activeWorkspace?.role || "VIEWER";

  return (
    <div className="space-y-6">
      {/* Role Capabilities Card */}
      <Card>
        <CardHeader>
          <div>
            <div className="flex items-center gap-2">
              <CardTitle>Workspace Role Permissions</CardTitle>
              <Badge variant="brand" size="sm">
                Your Role: {formatRole(currentRole)}
              </Badge>
            </div>
            <CardDescription>
              Capabilities associated with each role in the workspace.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {/* Viewer */}
            <div
              className={`rounded-xl border p-4 space-y-2 ${
                currentRole === "VIEWER"
                  ? "border-brand-300 bg-brand-50/30 shadow-2xs"
                  : "border-slate-200/80 bg-slate-50/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900">Viewer</span>
                {currentRole === "VIEWER" && (
                  <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                    Your Role
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 leading-normal">
                Can search documents, read verified knowledge, and chat with the AI assistant. Read-only permissions.
              </p>
              <ul className="text-[11px] text-slate-600 space-y-1 pt-1 border-t border-slate-200/60">
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Read documents
                </li>
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Chat & citations
                </li>
                <li className="flex items-center gap-1.5 text-slate-400">
                  <span>✕</span> Upload documents
                </li>
              </ul>
            </div>

            {/* Contributor */}
            <div
              className={`rounded-xl border p-4 space-y-2 ${
                currentRole === "CONTRIBUTOR"
                  ? "border-brand-300 bg-brand-50/30 shadow-2xs"
                  : "border-slate-200/80 bg-slate-50/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900">Contributor</span>
                {currentRole === "CONTRIBUTOR" && (
                  <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                    Your Role
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 leading-normal">
                Can upload PDFs, update document metadata, search, and chat with the AI assistant.
              </p>
              <ul className="text-[11px] text-slate-600 space-y-1 pt-1 border-t border-slate-200/60">
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Read documents
                </li>
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Upload & index PDFs
                </li>
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Chat & citations
                </li>
              </ul>
            </div>

            {/* Workspace Admin */}
            <div
              className={`rounded-xl border p-4 space-y-2 ${
                currentRole === "WORKSPACE_ADMIN"
                  ? "border-brand-300 bg-brand-50/30 shadow-2xs"
                  : "border-slate-200/80 bg-slate-50/50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-900">Workspace Admin</span>
                {currentRole === "WORKSPACE_ADMIN" && (
                  <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                    Your Role
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 leading-normal">
                Full administrative control over workspace settings, members, document ACLs, and archiving.
              </p>
              <ul className="text-[11px] text-slate-600 space-y-1 pt-1 border-t border-slate-200/60">
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Manage workspace members
                </li>
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Delete documents & ACLs
                </li>
                <li className="flex items-center gap-1.5 text-emerald-700">
                  <span>✓</span> Audit & telemetry access
                </li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Document Access & ACL Governance Card */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Document-Level Access Controls (ACL)</CardTitle>
            <CardDescription>
              In addition to workspace roles, individual documents can be restricted to specific users or roles.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-4 space-y-3">
            <p className="text-xs text-slate-600 leading-normal">
              Documents inherit workspace-wide visibility by default. Workspace Administrators can attach Access Control Lists (ACLs) to confidential documents to grant or restrict READ, WRITE, or ADMIN permissions to specific team members.
            </p>
            {onNavigateToDocuments && (
              <div className="pt-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onNavigateToDocuments}
                  className="font-medium text-xs"
                >
                  Go to Documents Library to inspect ACLs →
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
