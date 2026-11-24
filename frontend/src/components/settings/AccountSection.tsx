import type { User, UserWorkspace } from "../../types";
import { formatRole, getInitials, getUserDisplayName } from "../../utils/format";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, Button, Badge } from "../ui";

type AccountSectionProps = {
  user: User | null;
  activeWorkspace: UserWorkspace | null;
  onLogout: () => Promise<void>;
};

export function AccountSection({ user, activeWorkspace, onLogout }: AccountSectionProps) {
  if (!user) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-xs text-slate-500">
        No active account authenticated.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* User Profile Card */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Profile & Account Identity</CardTitle>
            <CardDescription>
              Authenticated credentials, identity details, and platform access memberships.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-6">
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-brand-50 text-brand-700 text-lg font-bold border border-brand-200/80 shadow-2xs">
              {getInitials(user)}
            </span>
            <div className="min-w-0 space-y-0.5">
              <h3 className="text-sm font-bold text-slate-900 truncate">
                {getUserDisplayName(user)}
              </h3>
              <p className="text-xs text-slate-500 truncate">{user.email}</p>
              <p className="text-[10px] font-mono text-slate-400 select-all">User ID: {user.id}</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-2 border-t border-slate-100">
            <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-3">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Account Status</span>
              <p className="text-xs font-semibold text-emerald-700 mt-0.5">
                {user.is_active ? "Active & Verified" : "Inactive"}
              </p>
            </div>

            <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-3">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Current Workspace</span>
              <p className="text-xs font-semibold text-slate-800 mt-0.5 truncate">
                {activeWorkspace?.name || "None"} ({formatRole(activeWorkspace?.role)})
              </p>
            </div>
          </div>

          {/* Enrolled Organizations */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-slate-900">Enrolled Organizations</h4>
            <div className="rounded-xl border border-slate-200/80 overflow-hidden divide-y divide-slate-100 bg-white">
              {user.organizations?.map((org) => (
                <div key={org.id} className="flex items-center justify-between p-3 text-xs">
                  <div>
                    <p className="font-semibold text-slate-900">{org.name}</p>
                    <p className="text-[11px] font-mono text-slate-400">{org.slug}</p>
                  </div>
                  <Badge variant={org.role === "OWNER" ? "brand" : "neutral"} size="sm">
                    {formatRole(org.role)}
                  </Badge>
                </div>
              ))}
              {(!user.organizations || user.organizations.length === 0) && (
                <p className="p-3 text-xs text-slate-400">No organizations found.</p>
              )}
            </div>
          </div>

          {/* Sign Out CTA */}
          <div className="pt-4 border-t border-slate-100 flex justify-between items-center">
            <p className="text-[11px] text-slate-400">
              Sign out to invalidate active session tokens and transient evidence cache.
            </p>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={onLogout}
              className="!border-slate-300 text-rose-700 hover:!bg-rose-50 hover:!text-rose-800"
            >
              Sign out
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
