import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { PageShell, PageHeader } from "../components/layout";
import { Toast } from "../components/ui";
import {
  SettingsNavigation,
  SettingsOverview,
  WorkspaceGeneralSection,
  WorkspaceMembersSection,
  WorkspaceAccessSection,
  OrganizationMembersSection,
  OrganizationWorkspacesSection,
  SecuritySection,
  OperationsSection,
  AccountSection,
  type SettingsSectionId,
} from "../components/settings";

function isValidSection(sec: string): sec is SettingsSectionId {
  return [
    "overview",
    "workspace-general",
    "workspace-members",
    "workspace-access",
    "organization-members",
    "organization-workspaces",
    "security",
    "operations",
    "account",
  ].includes(sec);
}

function parseSectionFromUrl(): SettingsSectionId {
  const path = window.location.pathname.replace(/\/+$/, "");
  const searchParams = new URLSearchParams(window.location.search);
  const paramSection = searchParams.get("section");
  if (paramSection && isValidSection(paramSection)) {
    return paramSection;
  }

  if (path === "/settings/overview") return "overview";
  if (path === "/settings/workspace" || path === "/settings/workspace/general" || path === "/settings/workspace-general")
    return "workspace-general";
  if (path === "/settings/workspace/members" || path === "/settings/members" || path === "/settings/workspace-members")
    return "workspace-members";
  if (path === "/settings/workspace/access" || path === "/settings/access" || path === "/settings/workspace-access")
    return "workspace-access";
  if (path === "/settings/organization/members" || path === "/settings/organization-members")
    return "organization-members";
  if (path === "/settings/organization/workspaces" || path === "/settings/workspaces" || path === "/settings/organization-workspaces")
    return "organization-workspaces";
  if (path === "/settings/security" || path === "/settings/audit-logs") return "security";
  if (path === "/settings/operations" || path === "/settings/observability") return "operations";
  if (path === "/settings/account" || path === "/settings/profile") return "account";

  return "overview";
}

export function WorkspaceSettingsPage() {
  const {
    user,
    activeWorkspace,
    availableWorkspaces,
    setActiveWorkspace,
    refreshWorkspaces,
    isWorkspaceAdmin,
    logout,
  } = useAuth();

  const [activeSection, setActiveSection] = useState<SettingsSectionId>(() => parseSectionFromUrl());
  const [successToast, setSuccessToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  const activeOrg =
    user?.organizations?.find((o) => o.id === activeWorkspace?.organization_id) ||
    user?.organizations?.[0] ||
    null;

  const isOrgAdminOrOwner = activeOrg?.role === "OWNER" || activeOrg?.role === "ADMIN";
  const isOrgOwner = activeOrg?.role === "OWNER";

  // Keep state in sync with popstate navigation
  useEffect(() => {
    function onPopState() {
      setActiveSection(parseSectionFromUrl());
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Role-aware safety redirect if user lacks permission for target section
  useEffect(() => {
    if (
      (activeSection === "organization-members" || activeSection === "organization-workspaces") &&
      !isOrgAdminOrOwner
    ) {
      handleSelectSection("overview");
    } else if (
      (activeSection === "security" || activeSection === "operations") &&
      !isWorkspaceAdmin &&
      !isOrgAdminOrOwner
    ) {
      handleSelectSection("overview");
    }
  }, [activeSection, isWorkspaceAdmin, isOrgAdminOrOwner]);

  function handleSelectSection(section: SettingsSectionId) {
    setActiveSection(section);
    const targetUrl = section === "overview" ? "/settings" : `/settings?section=${section}`;
    if (window.location.pathname + window.location.search !== targetUrl) {
      window.history.pushState({}, "", targetUrl);
    }
  }

  function getSectionTitle(sec: SettingsSectionId): { title: string; description: string } {
    switch (sec) {
      case "overview":
        return {
          title: "Settings & Administration",
          description: "Manage workspace configuration, team permissions, organization governance, and system operations.",
        };
      case "workspace-general":
        return {
          title: "Workspace Configuration",
          description: `Configure name, slug, and lifecycle state for "${activeWorkspace?.name || "Workspace"}".`,
        };
      case "workspace-members":
        return {
          title: "Workspace Team Members",
          description: `Manage team access, permissions, and roles in "${activeWorkspace?.name || "Workspace"}".`,
        };
      case "workspace-access":
        return {
          title: "Workspace Access & Permissions",
          description: "Review capability levels and document access governance.",
        };
      case "organization-members":
        return {
          title: "Organization Members",
          description: `Manage user enrollment and roles for ${activeOrg?.name || "your organization"}.`,
        };
      case "organization-workspaces":
        return {
          title: "Workspaces Directory",
          description: `Manage and provision knowledge workspaces within ${activeOrg?.name || "your organization"}.`,
        };
      case "security":
        return {
          title: "Security & Audit Logs",
          description: "Review tamper-evident audit logs and cryptographic verification telemetry.",
        };
      case "operations":
        return {
          title: "Platform Operations & Telemetry",
          description: "Monitor query performance, traces, alerts, and telemetry retention.",
        };
      case "account":
        return {
          title: "Account & Profile",
          description: "Signed-in credentials, user identity, and session controls.",
        };
    }
  }

  const { title, description } = getSectionTitle(activeSection);

  return (
    <PageShell>
      <PageHeader
        title={title}
        description={description}
      />

      {/* Global Notifications */}
      {errorToast && (
        <Toast
          type="error"
          message={errorToast}
          onClose={() => setErrorToast(null)}
        />
      )}
      {successToast && (
        <Toast
          type="success"
          message={successToast}
          onClose={() => setSuccessToast(null)}
        />
      )}

      {/* 2-Column Responsive Layout */}
      <div className="flex flex-col lg:flex-row gap-6 items-start">
        {/* Left Settings Navigation Bar */}
        <aside className="w-full lg:w-60 shrink-0">
          <div className="rounded-2xl border border-slate-200/90 bg-white p-3 sm:p-4 shadow-2xs">
            <SettingsNavigation
              activeSection={activeSection}
              onSelectSection={handleSelectSection}
              isWorkspaceAdmin={isWorkspaceAdmin}
              isOrgAdminOrOwner={isOrgAdminOrOwner}
              isOrgOwner={isOrgOwner}
            />
          </div>
        </aside>

        {/* Right Active Section Content Area */}
        <main className="flex-1 min-w-0 w-full">
          {activeSection === "overview" && (
            <SettingsOverview
              user={user}
              activeWorkspace={activeWorkspace}
              isWorkspaceAdmin={isWorkspaceAdmin}
              isOrgAdminOrOwner={isOrgAdminOrOwner}
              onNavigateSection={handleSelectSection}
            />
          )}

          {activeSection === "workspace-general" && (
            <WorkspaceGeneralSection
              activeWorkspace={activeWorkspace}
              isWorkspaceAdmin={isWorkspaceAdmin}
              onWorkspaceUpdated={refreshWorkspaces}
              onNotifySuccess={(msg) => setSuccessToast(msg)}
              onNotifyError={(msg) => setErrorToast(msg)}
            />
          )}

          {activeSection === "workspace-members" && (
            <WorkspaceMembersSection
              activeWorkspace={activeWorkspace}
              currentUser={user}
              isWorkspaceAdmin={isWorkspaceAdmin}
              onNotifySuccess={(msg) => setSuccessToast(msg)}
              onNotifyError={(msg) => setErrorToast(msg)}
            />
          )}

          {activeSection === "workspace-access" && (
            <WorkspaceAccessSection
              activeWorkspace={activeWorkspace}
              onNavigateToDocuments={() => {
                window.history.pushState({}, "", "/documents");
                window.dispatchEvent(new PopStateEvent("popstate"));
              }}
            />
          )}

          {activeSection === "organization-members" && isOrgAdminOrOwner && (
            <OrganizationMembersSection
              activeOrg={activeOrg}
              currentUser={user}
              isOrgOwner={isOrgOwner}
              onNotifySuccess={(msg) => setSuccessToast(msg)}
              onNotifyError={(msg) => setErrorToast(msg)}
            />
          )}

          {activeSection === "organization-workspaces" && isOrgAdminOrOwner && (
            <OrganizationWorkspacesSection
              activeOrg={activeOrg}
              activeWorkspace={activeWorkspace}
              availableWorkspaces={availableWorkspaces}
              onSelectWorkspace={setActiveWorkspace}
              onRefreshWorkspaces={refreshWorkspaces}
              onNotifySuccess={(msg) => setSuccessToast(msg)}
              onNotifyError={(msg) => setErrorToast(msg)}
            />
          )}

          {activeSection === "security" && (isWorkspaceAdmin || isOrgAdminOrOwner) && (
            <SecuritySection
              activeWorkspace={activeWorkspace}
              isOrgAdminOrOwner={isOrgAdminOrOwner}
            />
          )}

          {activeSection === "operations" && (isWorkspaceAdmin || isOrgAdminOrOwner) && (
            <OperationsSection
              activeWorkspace={activeWorkspace}
              isOrgAdminOrOwner={isOrgAdminOrOwner}
            />
          )}

          {activeSection === "account" && (
            <AccountSection
              user={user}
              activeWorkspace={activeWorkspace}
              onLogout={logout}
            />
          )}
        </main>
      </div>
    </PageShell>
  );
}
