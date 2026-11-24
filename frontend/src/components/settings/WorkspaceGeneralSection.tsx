import { useEffect, useState } from "react";
import type { UserWorkspace } from "../../types";
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
} from "../ui";

type WorkspaceGeneralSectionProps = {
  activeWorkspace: UserWorkspace | null;
  isWorkspaceAdmin: boolean;
  onWorkspaceUpdated: () => Promise<void>;
  onNotifySuccess: (msg: string) => void;
  onNotifyError: (msg: string) => void;
};

export function WorkspaceGeneralSection({
  activeWorkspace,
  isWorkspaceAdmin,
  onWorkspaceUpdated,
  onNotifySuccess,
  onNotifyError,
}: WorkspaceGeneralSectionProps) {
  const [name, setName] = useState(activeWorkspace?.name || "");
  const [slug, setSlug] = useState(activeWorkspace?.slug || "");
  const [isSaving, setIsSaving] = useState(false);
  const [isArchiving, setIsArchiving] = useState(false);
  const [showArchiveModal, setShowArchiveModal] = useState(false);
  const [showRestoreModal, setShowRestoreModal] = useState(false);

  useEffect(() => {
    if (activeWorkspace) {
      setName(activeWorkspace.name);
      setSlug(activeWorkspace.slug);
    }
  }, [activeWorkspace]);

  if (!activeWorkspace) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
        No active workspace selected.
      </div>
    );
  }

  async function handleSaveDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!activeWorkspace || !name.trim()) return;
    setIsSaving(true);

    try {
      await api.updateWorkspace(activeWorkspace.id, {
        name: name.trim(),
        slug: slug.trim() || undefined,
      });
      await onWorkspaceUpdated();
      onNotifySuccess("Workspace details updated successfully.");
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsSaving(false);
    }
  }

  async function handleConfirmArchive() {
    if (!activeWorkspace) return;
    setIsArchiving(true);
    try {
      await api.archiveWorkspace(activeWorkspace.id);
      await onWorkspaceUpdated();
      setShowArchiveModal(false);
      onNotifySuccess(`Workspace "${activeWorkspace.name}" archived.`);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsArchiving(false);
    }
  }

  async function handleConfirmRestore() {
    if (!activeWorkspace) return;
    setIsArchiving(true);
    try {
      await api.updateWorkspace(activeWorkspace.id, {
        is_archived: false,
      });
      await onWorkspaceUpdated();
      setShowRestoreModal(false);
      onNotifySuccess(`Workspace "${activeWorkspace.name}" restored successfully.`);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsArchiving(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Workspace Overview & Identity Card */}
      <Card>
        <CardHeader>
          <div>
            <div className="flex items-center gap-2">
              <CardTitle>{activeWorkspace.name}</CardTitle>
              <Badge variant="brand" size="sm">
                Your Role: {formatRole(activeWorkspace.role)}
              </Badge>
            </div>
            <CardDescription>
              Manage basic details, slug identifiers, and lifecycle state for this workspace.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent>
          <form onSubmit={handleSaveDetails} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Input
                id="workspace-general-name"
                label="Workspace Name"
                type="text"
                required
                value={name}
                disabled={!isWorkspaceAdmin || isSaving}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Legal Research"
                helperText="Human-readable name displayed across the assistant navigation."
              />

              <Input
                id="workspace-general-slug"
                label="Workspace Slug"
                type="text"
                required
                value={slug}
                disabled={!isWorkspaceAdmin || isSaving}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="e.g. legal-research"
                helperText="URL-friendly identifier unique to your organization."
              />
            </div>

            <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs">
              <div>
                <span className="font-semibold text-slate-700">Workspace Identifier:</span>
                <span className="font-mono text-slate-500 ml-2 select-all">{activeWorkspace.id}</span>
              </div>
              <div className="text-[11px] text-slate-500">
                Organization: <span className="font-mono text-slate-600">{activeWorkspace.organization_id}</span>
              </div>
            </div>

            {isWorkspaceAdmin ? (
              <div className="flex justify-end pt-2">
                <Button type="submit" variant="primary" size="sm" isLoading={isSaving}>
                  Save Workspace Changes
                </Button>
              </div>
            ) : (
              <p className="text-[11px] text-slate-400 italic pt-1">
                You have read-only access to this workspace. Only Workspace Admins can edit settings.
              </p>
            )}
          </form>
        </CardContent>
      </Card>

      {/* Danger / Lifecycle Zone */}
      {isWorkspaceAdmin && (
        <Card className="border-slate-200">
          <CardHeader>
            <div>
              <CardTitle>Workspace Lifecycle</CardTitle>
              <CardDescription>
                Archive this workspace when it is no longer actively used. Archiving restricts normal operations.
              </CardDescription>
            </div>
          </CardHeader>

          <CardContent>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50/40 p-4">
              <div className="space-y-1">
                <p className="text-xs font-semibold text-rose-900">Archive this workspace</p>
                <p className="text-[11px] text-rose-700 leading-normal">
                  Its content will no longer be available for normal workspace operations or assistant queries.
                </p>
              </div>
              <Button
                type="button"
                variant="danger"
                size="sm"
                onClick={() => setShowArchiveModal(true)}
                className="shrink-0"
              >
                Archive Workspace
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Archive Confirmation Modal */}
      <Modal
        isOpen={showArchiveModal}
        onClose={() => setShowArchiveModal(false)}
        title="Archive Workspace"
        description="Are you sure you want to archive this workspace?"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setShowArchiveModal(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isArchiving}
              onClick={handleConfirmArchive}
            >
              Archive Workspace
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-xs text-slate-600">
          <p>
            You are about to archive <strong className="text-slate-900">{activeWorkspace.name}</strong>.
          </p>
          <p className="rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-800 border border-amber-200/80">
            Its content will no longer be available for normal workspace operations. Organization Admins can restore it later if needed.
          </p>
        </div>
      </Modal>

      {/* Restore Confirmation Modal */}
      <Modal
        isOpen={showRestoreModal}
        onClose={() => setShowRestoreModal(false)}
        title="Restore Workspace"
        description="Reactivate this archived workspace for normal operations."
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setShowRestoreModal(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isArchiving}
              onClick={handleConfirmRestore}
            >
              Restore Workspace
            </Button>
          </>
        }
      >
        <p className="text-xs text-slate-600">
          Reactivating <strong className="text-slate-900">{activeWorkspace.name}</strong> will restore full document access, search, and assistant capabilities.
        </p>
      </Modal>
    </div>
  );
}
