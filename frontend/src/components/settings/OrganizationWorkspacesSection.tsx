import { useEffect, useState } from "react";
import type { UserOrg, UserWorkspace, WorkspaceItem } from "../../types";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import { formatRole } from "../../utils/format";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Input,
  Badge,
  Modal,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
} from "../ui";

type OrganizationWorkspacesSectionProps = {
  activeOrg: UserOrg | null;
  activeWorkspace: UserWorkspace | null;
  availableWorkspaces: UserWorkspace[];
  onSelectWorkspace: (ws: UserWorkspace) => void;
  onRefreshWorkspaces: () => Promise<void>;
  onNotifySuccess: (msg: string) => void;
  onNotifyError: (msg: string) => void;
};

export function OrganizationWorkspacesSection({
  activeOrg,
  activeWorkspace,
  availableWorkspaces,
  onSelectWorkspace,
  onRefreshWorkspaces,
  onNotifySuccess,
  onNotifyError,
}: OrganizationWorkspacesSectionProps) {
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [loading, setLoading] = useState(false);

  // Create Workspace Modal State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newWsName, setNewWsName] = useState("");
  const [newWsSlug, setNewWsSlug] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Archive / Restore Modal State
  const [wsToArchive, setWsToArchive] = useState<WorkspaceItem | null>(null);
  const [wsToRestore, setWsToRestore] = useState<WorkspaceItem | null>(null);
  const [isMutating, setIsMutating] = useState(false);

  async function loadWorkspaces() {
    setLoading(true);
    try {
      const res = await api.listWorkspaces();
      setWorkspaces(res.workspaces);
    } catch (err) {
      onNotifyError(userFacingError(err, "list"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadWorkspaces();
  }, [activeOrg?.id]);

  async function handleCreateWorkspace(e: React.FormEvent) {
    e.preventDefault();
    if (!activeOrg || !newWsName.trim()) return;
    setIsCreating(true);

    try {
      const created = await api.createWorkspace({
        organization_id: activeOrg.id,
        name: newWsName.trim(),
        slug: newWsSlug.trim() || undefined,
      });
      await onRefreshWorkspaces();
      await loadWorkspaces();
      setShowCreateModal(false);
      setNewWsName("");
      setNewWsSlug("");
      onNotifySuccess(`Workspace "${created.name}" created successfully.`);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsCreating(false);
    }
  }

  async function handleConfirmArchive() {
    if (!wsToArchive) return;
    setIsMutating(true);

    try {
      await api.archiveWorkspace(wsToArchive.id);
      await onRefreshWorkspaces();
      await loadWorkspaces();
      onNotifySuccess(`Workspace "${wsToArchive.name}" archived.`);
      setWsToArchive(null);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsMutating(false);
    }
  }

  async function handleConfirmRestore() {
    if (!wsToRestore) return;
    setIsMutating(true);

    try {
      await api.updateWorkspace(wsToRestore.id, {
        is_archived: false,
      });
      await onRefreshWorkspaces();
      await loadWorkspaces();
      onNotifySuccess(`Workspace "${wsToRestore.name}" restored.`);
      setWsToRestore(null);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsMutating(false);
    }
  }

  function handleSwitch(ws: WorkspaceItem) {
    const matched = availableWorkspaces.find((w) => w.id === ws.id) || {
      id: ws.id,
      organization_id: ws.organization_id,
      name: ws.name,
      slug: ws.slug,
      role: ws.role || "VIEWER",
    };
    onSelectWorkspace(matched);
    onNotifySuccess(`Switched active workspace to "${ws.name}".`);
  }

  if (!activeOrg) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
        No active organization found.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>Workspaces Directory ({activeOrg.name})</CardTitle>
                <Badge variant="brand" size="sm">
                  {workspaces.length} {workspaces.length === 1 ? "Workspace" : "Workspaces"}
                </Badge>
              </div>
              <CardDescription>
                Create, archive, or switch between isolated knowledge workspaces in your organization.
              </CardDescription>
            </div>

            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              className="self-start sm:self-auto shrink-0"
            >
              + Create Workspace
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {loading ? (
            <div className="py-12 text-center text-xs text-slate-400" role="status">
              <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-600 border-t-transparent mb-2" />
              <p>Loading organization workspaces…</p>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/80 overflow-hidden bg-white">
              <Table>
                <TableHeader>
                  <tr>
                    <TableHead>Workspace Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Your Role</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </tr>
                </TableHeader>
                <TableBody>
                  {workspaces.map((ws) => {
                    const isActive = ws.id === activeWorkspace?.id;
                    const isArchived = Boolean(ws.is_archived);

                    return (
                      <TableRow key={ws.id}>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-900">{ws.name}</span>
                            {isActive && (
                              <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                                Active
                              </span>
                            )}
                          </div>
                        </TableCell>

                        <TableCell>
                          <span className="font-mono text-xs text-slate-500">{ws.slug}</span>
                        </TableCell>

                        <TableCell>
                          <Badge variant={isArchived ? "warning" : "success"} size="sm">
                            {isArchived ? "Archived" : "Active"}
                          </Badge>
                        </TableCell>

                        <TableCell>
                          <span className="text-xs text-slate-600 font-medium">
                            {formatRole(ws.role)}
                          </span>
                        </TableCell>

                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {!isActive && (
                              <Button
                                type="button"
                                variant="secondary"
                                size="sm"
                                onClick={() => handleSwitch(ws)}
                                className="!text-xs"
                              >
                                Switch
                              </Button>
                            )}

                            {isArchived ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setWsToRestore(ws)}
                                className="!text-xs text-emerald-700 hover:!bg-emerald-50"
                              >
                                Restore
                              </Button>
                            ) : (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setWsToArchive(ws)}
                                className="!text-xs text-rose-600 hover:!bg-rose-50"
                              >
                                Archive
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}

                  {workspaces.length === 0 && (
                    <TableEmpty colSpan={5} message="No workspaces found in this organization." />
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Workspace Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="Create New Workspace"
        description="Provision an isolated knowledge base and conversation workspace."
      >
        <form onSubmit={handleCreateWorkspace} className="space-y-4">
          <Input
            id="create-ws-name"
            label="Workspace Name"
            type="text"
            required
            value={newWsName}
            onChange={(e) => {
              setNewWsName(e.target.value);
              if (!newWsSlug) {
                setNewWsSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "-"));
              }
            }}
            placeholder="e.g. Finance & Auditing"
          />

          <Input
            id="create-ws-slug"
            label="Workspace Slug (Optional)"
            type="text"
            value={newWsSlug}
            onChange={(e) => setNewWsSlug(e.target.value)}
            placeholder="e.g. finance-auditing"
            helperText="Auto-generated if left empty."
          />

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowCreateModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isCreating}>
              Create Workspace
            </Button>
          </div>
        </form>
      </Modal>

      {/* Archive Confirmation Modal */}
      <Modal
        isOpen={Boolean(wsToArchive)}
        onClose={() => setWsToArchive(null)}
        title="Archive Workspace"
        description="Confirm workspace archiving"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setWsToArchive(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isMutating}
              onClick={handleConfirmArchive}
            >
              Archive workspace
            </Button>
          </>
        }
      >
        {wsToArchive && (
          <div className="space-y-3 text-xs text-slate-600">
            <p>
              Archive <strong className="text-slate-900">{wsToArchive.name}</strong>?
            </p>
            <p className="rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-800 border border-amber-200/80">
              Its content will no longer be available for normal workspace operations. You can restore it anytime from this list.
            </p>
          </div>
        )}
      </Modal>

      {/* Restore Confirmation Modal */}
      <Modal
        isOpen={Boolean(wsToRestore)}
        onClose={() => setWsToRestore(null)}
        title="Restore Workspace"
        description="Confirm workspace reactivation"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setWsToRestore(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isMutating}
              onClick={handleConfirmRestore}
            >
              Restore workspace
            </Button>
          </>
        }
      >
        {wsToRestore && (
          <p className="text-xs text-slate-600">
            Reactivating <strong className="text-slate-900">{wsToRestore.name}</strong> will re-enable full search, document access, and AI chat capabilities for workspace members.
          </p>
        )}
      </Modal>
    </div>
  );
}
