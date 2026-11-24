import { useEffect, useState, useMemo } from "react";
import type { WorkspaceMember, UserWorkspace, User } from "../../types";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import { formatRole, getInitials } from "../../utils/format";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Input,
  Select,
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

type WorkspaceMembersSectionProps = {
  activeWorkspace: UserWorkspace | null;
  currentUser: User | null;
  isWorkspaceAdmin: boolean;
  onNotifySuccess: (msg: string) => void;
  onNotifyError: (msg: string) => void;
};

export function WorkspaceMembersSection({
  activeWorkspace,
  currentUser,
  isWorkspaceAdmin,
  onNotifySuccess,
  onNotifyError,
}: WorkspaceMembersSectionProps) {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Add Member State
  const [showAddModal, setShowAddModal] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("CONTRIBUTOR");
  const [isAdding, setIsAdding] = useState(false);

  // Remove Member State
  const [memberToRemove, setMemberToRemove] = useState<WorkspaceMember | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  // Load members on mount or workspace change
  useEffect(() => {
    if (!activeWorkspace) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const res = await api.listWorkspaceMembers(activeWorkspace!.id);
        if (!cancelled) setMembers(res.members);
      } catch (err) {
        if (!cancelled) onNotifyError(userFacingError(err, "list"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [activeWorkspace?.id]);

  // Client-side search filtering by name and email
  const filteredMembers = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return members;
    return members.filter(
      (m) =>
        (m.full_name && m.full_name.toLowerCase().includes(q)) ||
        (m.email && m.email.toLowerCase().includes(q))
    );
  }, [members, searchQuery]);

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    if (!activeWorkspace || !newEmail.trim()) return;
    setIsAdding(true);

    try {
      const added = await api.addWorkspaceMember(activeWorkspace.id, {
        email: newEmail.trim(),
        role: newRole,
      });
      setMembers((prev) => [...prev.filter((m) => m.id !== added.id), added]);
      setShowAddModal(false);
      setNewEmail("");
      setNewRole("CONTRIBUTOR");
      onNotifySuccess(`Added ${added.email} to workspace as ${formatRole(added.role)}.`);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsAdding(false);
    }
  }

  async function handleRoleChange(userId: string, targetRole: string) {
    if (!activeWorkspace) return;

    try {
      const updated = await api.updateWorkspaceMemberRole(activeWorkspace.id, userId, targetRole);
      setMembers((prev) => prev.map((m) => (m.user_id === userId ? updated : m)));
      onNotifySuccess("Member role updated successfully.");
    } catch (err) {
      onNotifyError(userFacingError(err));
    }
  }

  async function handleConfirmRemove() {
    if (!activeWorkspace || !memberToRemove) return;
    setIsRemoving(true);

    try {
      await api.removeWorkspaceMember(activeWorkspace.id, memberToRemove.user_id);
      setMembers((prev) => prev.filter((m) => m.user_id !== memberToRemove.user_id));
      onNotifySuccess(`Removed ${memberToRemove.email} from workspace.`);
      setMemberToRemove(null);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsRemoving(false);
    }
  }

  if (!activeWorkspace) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
        No active workspace selected.
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
                <CardTitle>Workspace Members</CardTitle>
                <Badge variant="neutral" size="sm">
                  {members.length} {members.length === 1 ? "Member" : "Members"}
                </Badge>
              </div>
              <CardDescription>
                Users with access to search, chat, and upload knowledge in {activeWorkspace.name}.
              </CardDescription>
            </div>

            {isWorkspaceAdmin && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setShowAddModal(true)}
                className="self-start sm:self-auto shrink-0"
              >
                + Add Member
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Member Search Bar */}
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="w-full sm:max-w-xs">
              <Input
                id="ws-member-search"
                type="search"
                placeholder="Search by name or email…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            {searchQuery && (
              <span className="text-[11px] text-slate-500 self-start sm:self-auto">
                Showing {filteredMembers.length} of {members.length} members
              </span>
            )}
          </div>

          {/* Members Table */}
          {loading ? (
            <div className="py-12 text-center text-xs text-slate-400" role="status">
              <div className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brand-600 border-t-transparent mb-2" />
              <p>Loading workspace members…</p>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/80 overflow-hidden bg-white">
              <Table>
                <TableHeader>
                  <tr>
                    <TableHead>Member</TableHead>
                    <TableHead>Workspace Role</TableHead>
                    {isWorkspaceAdmin && <TableHead className="text-right">Actions</TableHead>}
                  </tr>
                </TableHeader>
                <TableBody>
                  {filteredMembers.map((member) => {
                    const isSelf = member.user_id === currentUser?.id;
                    return (
                      <TableRow key={member.id || member.user_id}>
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-700 text-xs font-bold border border-slate-200">
                              {getInitials(member)}
                            </span>
                            <div className="min-w-0">
                              <p className="font-semibold text-slate-900 truncate">
                                {member.full_name || member.email}
                                {isSelf && (
                                  <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                                    You
                                  </span>
                                )}
                              </p>
                              <p className="text-[11px] text-slate-500 truncate">{member.email}</p>
                            </div>
                          </div>
                        </TableCell>

                        <TableCell>
                          {isWorkspaceAdmin && !isSelf ? (
                            <select
                              value={member.role}
                              onChange={(e) => handleRoleChange(member.user_id, e.target.value)}
                              aria-label={`Change role for ${member.full_name || member.email}`}
                              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-2xs hover:border-slate-300 focus:border-brand-500 focus:outline-none cursor-pointer"
                            >
                              <option value="VIEWER">Viewer (Read & Chat)</option>
                              <option value="CONTRIBUTOR">Contributor (Upload & Chat)</option>
                              <option value="WORKSPACE_ADMIN">Workspace Admin</option>
                            </select>
                          ) : (
                            <Badge variant={member.role === "WORKSPACE_ADMIN" ? "brand" : "neutral"} size="sm">
                              {formatRole(member.role)}
                            </Badge>
                          )}
                        </TableCell>

                        {isWorkspaceAdmin && (
                          <TableCell className="text-right">
                            {!isSelf && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setMemberToRemove(member)}
                                className="!text-rose-600 hover:!bg-rose-50 font-medium"
                              >
                                Remove
                              </Button>
                            )}
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })}

                  {filteredMembers.length === 0 && (
                    <TableEmpty
                      colSpan={isWorkspaceAdmin ? 3 : 2}
                      message={
                        searchQuery
                          ? `No members found matching "${searchQuery}".`
                          : "No explicit members found in this workspace."
                      }
                    />
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Add Member Modal */}
      <Modal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        title="Add Workspace Member"
        description="Grant an existing organization member access to this workspace."
      >
        <form onSubmit={handleAddMember} className="space-y-4">
          <Input
            id="add-ws-member-email"
            label="User Email or User ID"
            type="text"
            required
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="member@company.com"
            helperText="Must be an existing member enrolled in your organization."
          />

          <Select
            id="add-ws-member-role"
            label="Workspace Role"
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            options={[
              { value: "VIEWER", label: "Viewer — Can read documents and chat" },
              { value: "CONTRIBUTOR", label: "Contributor — Can upload documents and chat" },
              { value: "WORKSPACE_ADMIN", label: "Workspace Admin — Full workspace control" },
            ]}
          />

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowAddModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isAdding}>
              Add Member
            </Button>
          </div>
        </form>
      </Modal>

      {/* Remove Member Confirmation Modal */}
      <Modal
        isOpen={Boolean(memberToRemove)}
        onClose={() => setMemberToRemove(null)}
        title="Remove Member"
        description="Confirm removing member from workspace"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setMemberToRemove(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isRemoving}
              onClick={handleConfirmRemove}
            >
              Remove member
            </Button>
          </>
        }
      >
        {memberToRemove && (
          <div className="space-y-3 text-xs text-slate-600">
            <p>
              Remove <strong className="text-slate-900">{memberToRemove.full_name || memberToRemove.email}</strong> from{" "}
              <strong className="text-slate-900">{activeWorkspace.name}</strong>?
            </p>
            <p className="rounded-lg bg-rose-50 p-2.5 text-[11px] text-rose-800 border border-rose-200/80">
              They will lose access to this workspace's knowledge base, documents, and conversations immediately.
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
