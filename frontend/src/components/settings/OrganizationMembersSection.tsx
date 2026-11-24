import { useEffect, useState, useMemo } from "react";
import type { OrganizationMember, User, UserOrg } from "../../types";
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

type OrganizationMembersSectionProps = {
  activeOrg: UserOrg | null;
  currentUser: User | null;
  isOrgOwner: boolean;
  onNotifySuccess: (msg: string) => void;
  onNotifyError: (msg: string) => void;
};

export function OrganizationMembersSection({
  activeOrg,
  currentUser,
  isOrgOwner,
  onNotifySuccess,
  onNotifyError,
}: OrganizationMembersSectionProps) {
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Add Org Member State
  const [showAddModal, setShowAddModal] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("MEMBER");
  const [isAdding, setIsAdding] = useState(false);

  // Remove Member State
  const [memberToRemove, setMemberToRemove] = useState<OrganizationMember | null>(null);
  const [isRemoving, setIsRemoving] = useState(false);

  useEffect(() => {
    if (!activeOrg) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const res = await api.listOrgMembers(activeOrg!.id);
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
  }, [activeOrg?.id]);

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
    if (!activeOrg || !newEmail.trim()) return;
    setIsAdding(true);

    try {
      const added = await api.addOrgMember(activeOrg.id, {
        email: newEmail.trim(),
        role: newRole,
      });
      setMembers((prev) => [...prev.filter((m) => m.id !== added.id), added]);
      setShowAddModal(false);
      setNewEmail("");
      setNewRole("MEMBER");
      onNotifySuccess(`Added ${added.email} to organization as ${formatRole(added.role)}.`);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsAdding(false);
    }
  }

  async function handleRoleChange(userId: string, targetRole: string) {
    if (!activeOrg) return;

    try {
      const updated = await api.updateOrgMemberRole(activeOrg.id, userId, targetRole);
      setMembers((prev) => prev.map((m) => (m.user_id === userId ? updated : m)));
      onNotifySuccess("Organization member role updated successfully.");
    } catch (err) {
      onNotifyError(userFacingError(err));
    }
  }

  async function handleConfirmRemove() {
    if (!activeOrg || !memberToRemove) return;
    setIsRemoving(true);

    try {
      await api.removeOrgMember(activeOrg.id, memberToRemove.user_id);
      setMembers((prev) => prev.filter((m) => m.user_id !== memberToRemove.user_id));
      onNotifySuccess(`Removed ${memberToRemove.email} from organization.`);
      setMemberToRemove(null);
    } catch (err) {
      onNotifyError(userFacingError(err));
    } finally {
      setIsRemoving(false);
    }
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
                <CardTitle>Organization Members ({activeOrg.name})</CardTitle>
                <Badge variant="brand" size="sm">
                  {members.length} {members.length === 1 ? "Member" : "Members"}
                </Badge>
              </div>
              <CardDescription>
                Users enrolled in {activeOrg.name}. Organization members can be allocated to individual workspaces.
              </CardDescription>
            </div>

            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowAddModal(true)}
              className="self-start sm:self-auto shrink-0"
            >
              + Add to Organization
            </Button>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Member Search Bar */}
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
            <div className="w-full sm:max-w-xs">
              <Input
                id="org-member-search"
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
              <p>Loading organization members…</p>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/80 overflow-hidden bg-white">
              <Table>
                <TableHeader>
                  <tr>
                    <TableHead>Member</TableHead>
                    <TableHead>Organization Role</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
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
                          {!isSelf ? (
                            <select
                              value={member.role}
                              onChange={(e) => handleRoleChange(member.user_id, e.target.value)}
                              aria-label={`Change org role for ${member.full_name || member.email}`}
                              className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-2xs hover:border-slate-300 focus:border-brand-500 focus:outline-none cursor-pointer"
                            >
                              <option value="MEMBER">Member</option>
                              <option value="ADMIN">Organization Admin</option>
                              <option value="BILLING">Billing</option>
                              {isOrgOwner && <option value="OWNER">Owner</option>}
                            </select>
                          ) : (
                            <Badge variant="brand" size="sm">
                              {formatRole(member.role)}
                            </Badge>
                          )}
                        </TableCell>

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
                      </TableRow>
                    );
                  })}

                  {filteredMembers.length === 0 && (
                    <TableEmpty
                      colSpan={3}
                      message={
                        searchQuery
                          ? `No members found matching "${searchQuery}".`
                          : "No organization members found."
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
        title="Add Organization Member"
        description="Enroll a new user into your organization."
      >
        <form onSubmit={handleAddMember} className="space-y-4">
          <Input
            id="add-org-member-email"
            label="User Email or User ID"
            type="text"
            required
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="member@company.com"
          />

          <Select
            id="add-org-member-role"
            label="Organization Role"
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            options={[
              { value: "MEMBER", label: "Member — Standard platform user" },
              { value: "ADMIN", label: "Organization Admin — Manage team and workspaces" },
              { value: "BILLING", label: "Billing — View billing details" },
              ...(isOrgOwner ? [{ value: "OWNER", label: "Owner — Full organization governance" }] : []),
            ]}
          />

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowAddModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isAdding}>
              Add to Organization
            </Button>
          </div>
        </form>
      </Modal>

      {/* Remove Member Confirmation Modal */}
      <Modal
        isOpen={Boolean(memberToRemove)}
        onClose={() => setMemberToRemove(null)}
        title="Remove Member from Organization"
        description="Confirm removing member"
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
              <strong className="text-slate-900">{activeOrg.name}</strong>?
            </p>
            <p className="rounded-lg bg-rose-50 p-2.5 text-[11px] text-rose-800 border border-rose-200/80">
              They will immediately lose access to all workspaces and data across the entire organization.
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
