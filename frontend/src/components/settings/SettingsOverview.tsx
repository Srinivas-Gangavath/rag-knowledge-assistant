import type { SettingsSectionId } from "./types";
import { formatRole, getUserDisplayName } from "../../utils/format";
import type { User, UserWorkspace } from "../../types";
import { Badge, Button } from "../ui";

type SettingsOverviewProps = {
  user: User | null;
  activeWorkspace: UserWorkspace | null;
  isWorkspaceAdmin: boolean;
  isOrgAdminOrOwner: boolean;
  onNavigateSection: (section: SettingsSectionId) => void;
};

export function SettingsOverview({
  user,
  activeWorkspace,
  isWorkspaceAdmin,
  isOrgAdminOrOwner,
  onNavigateSection,
}: SettingsOverviewProps) {
  const activeOrg =
    user?.organizations?.find((o) => o.id === activeWorkspace?.organization_id) ||
    user?.organizations?.[0];

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="rounded-2xl border border-slate-200/90 bg-white p-5 sm:p-6 shadow-2xs">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-slate-900">Administration Overview</h2>
              <Badge variant="brand" size="sm">
                {formatRole(activeWorkspace?.role)}
              </Badge>
            </div>
            <p className="text-xs text-slate-500 mt-1 leading-normal">
              Manage workspace configuration, access permissions, team memberships, and compliance controls.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto shrink-0">
            <span className="text-[11px] text-slate-500">
              Active Workspace: <strong className="text-slate-800">{activeWorkspace?.name || "None"}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* Grid of Navigation Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {/* 1. Workspace General */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Workspace</span>
            </div>
            <h3 className="text-xs font-bold text-slate-900">General Settings</h3>
            <p className="text-[11px] text-slate-500 leading-normal">
              Workspace identifier, slug, status, and naming configuration for {activeWorkspace?.name}.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateSection("workspace-general")}
              className="!text-xs font-semibold text-brand-700 hover:!bg-brand-50"
            >
              Configure details →
            </Button>
          </div>
        </div>

        {/* 2. Workspace Members */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Team</span>
            </div>
            <h3 className="text-xs font-bold text-slate-900">Workspace Members</h3>
            <p className="text-[11px] text-slate-500 leading-normal">
              Manage team members who can search, chat, and upload knowledge in this workspace.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateSection("workspace-members")}
              className="!text-xs font-semibold text-brand-700 hover:!bg-brand-50"
            >
              Manage members →
            </Button>
          </div>
        </div>

        {/* 3. Access & Governance */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Governance</span>
            </div>
            <h3 className="text-xs font-bold text-slate-900">Access & Permissions</h3>
            <p className="text-[11px] text-slate-500 leading-normal">
              Understand workspace role capabilities (Admin, Contributor, Viewer) and document ACLs.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateSection("workspace-access")}
              className="!text-xs font-semibold text-brand-700 hover:!bg-brand-50"
            >
              View permissions →
            </Button>
          </div>
        </div>

        {/* 4. Organization Members (Org Admins/Owners) */}
        {isOrgAdminOrOwner && (
          <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                  </svg>
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">Organization</span>
              </div>
              <h3 className="text-xs font-bold text-slate-900">Organization Roster</h3>
              <p className="text-[11px] text-slate-500 leading-normal">
                Enrolled users across {activeOrg?.name || "your organization"}, org roles, and invitations.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigateSection("organization-members")}
                className="!text-xs font-semibold text-indigo-700 hover:!bg-indigo-50"
              >
                Manage org members →
              </Button>
            </div>
          </div>
        )}

        {/* 5. Workspaces Management (Org Admins/Owners) */}
        {isOrgAdminOrOwner && (
          <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                  </svg>
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500">Organization</span>
              </div>
              <h3 className="text-xs font-bold text-slate-900">Workspaces Directory</h3>
              <p className="text-[11px] text-slate-500 leading-normal">
                Create new isolated workspaces, archive obsolete ones, or switch active contexts.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigateSection("organization-workspaces")}
                className="!text-xs font-semibold text-indigo-700 hover:!bg-indigo-50"
              >
                Manage workspaces →
              </Button>
            </div>
          </div>
        )}

        {/* 6. Security & Audit Logs */}
        {(isWorkspaceAdmin || isOrgAdminOrOwner) && (
          <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600">Security</span>
              </div>
              <h3 className="text-xs font-bold text-slate-900">Audit Logs & Compliance</h3>
              <p className="text-[11px] text-slate-500 leading-normal">
                Immutable audit trail with cryptographic hash verification for compliance and governance.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigateSection("security")}
                className="!text-xs font-semibold text-emerald-700 hover:!bg-emerald-50"
              >
                Inspect audit logs →
              </Button>
            </div>
          </div>
        )}

        {/* 7. Platform Operations */}
        {(isWorkspaceAdmin || isOrgAdminOrOwner) && (
          <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-sky-600">Operations</span>
              </div>
              <h3 className="text-xs font-bold text-slate-900">Observability & Tracing</h3>
              <p className="text-[11px] text-slate-500 leading-normal">
                Query latency, token breakdown, trace timeline explorer, and automated retention cleanup.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigateSection("operations")}
                className="!text-xs font-semibold text-sky-700 hover:!bg-sky-50"
              >
                View operations →
              </Button>
            </div>
          </div>
        )}

        {/* 8. Profile & Identity */}
        <div className="flex flex-col justify-between rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs hover:border-brand-300 hover:shadow-xs transition-all">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Account</span>
            </div>
            <h3 className="text-xs font-bold text-slate-900">Profile & Identity</h3>
            <p className="text-[11px] text-slate-500 leading-normal">
              Signed in as <strong>{getUserDisplayName(user)}</strong> ({user?.email}).
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onNavigateSection("account")}
              className="!text-xs font-semibold text-slate-700 hover:!bg-slate-100"
            >
              Account details →
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
