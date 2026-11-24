import type { SettingsSectionId } from "./types";

type SettingsNavigationProps = {
  activeSection: SettingsSectionId;
  onSelectSection: (section: SettingsSectionId) => void;
  isWorkspaceAdmin: boolean;
  isOrgAdminOrOwner: boolean;
  isOrgOwner: boolean;
};

export function SettingsNavigation({
  activeSection,
  onSelectSection,
  isWorkspaceAdmin,
  isOrgAdminOrOwner,
}: SettingsNavigationProps) {
  const navGroups = [
    {
      id: "general",
      title: "Overview",
      items: [
        {
          id: "overview" as SettingsSectionId,
          label: "Settings Overview",
          icon: (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
            </svg>
          ),
        },
      ],
    },
    {
      id: "workspace",
      title: "Workspace",
      items: [
        {
          id: "workspace-general" as SettingsSectionId,
          label: "General Details",
          icon: (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          ),
        },
        {
          id: "workspace-members" as SettingsSectionId,
          label: "Workspace Members",
          icon: (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          ),
        },
        {
          id: "workspace-access" as SettingsSectionId,
          label: "Access & Governance",
          icon: (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          ),
        },
      ],
    },
    ...(isOrgAdminOrOwner
      ? [
          {
            id: "organization",
            title: "Organization",
            items: [
              {
                id: "organization-members" as SettingsSectionId,
                label: "Organization Members",
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                  </svg>
                ),
              },
              {
                id: "organization-workspaces" as SettingsSectionId,
                label: "Workspaces Management",
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
                  </svg>
                ),
              },
            ],
          },
        ]
      : []),
    ...(isWorkspaceAdmin || isOrgAdminOrOwner
      ? [
          {
            id: "security-ops",
            title: "Security & Operations",
            items: [
              {
                id: "security" as SettingsSectionId,
                label: "Audit Logs & Compliance",
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                ),
              },
              {
                id: "operations" as SettingsSectionId,
                label: "Platform Operations",
                icon: (
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                ),
              },
            ],
          },
        ]
      : []),
    {
      id: "account-group",
      title: "Account",
      items: [
        {
          id: "account" as SettingsSectionId,
          label: "Profile & Identity",
          icon: (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          ),
        },
      ],
    },
  ];

  return (
    <div>
      {/* Mobile Selector Bar */}
      <div className="mb-4 lg:hidden">
        <label htmlFor="mobile-settings-nav" className="block text-xs font-semibold text-slate-700 mb-1.5">
          Settings Section
        </label>
        <select
          id="mobile-settings-nav"
          value={activeSection}
          onChange={(e) => onSelectSection(e.target.value as SettingsSectionId)}
          className="w-full rounded-xl border border-slate-300 bg-white py-2 px-3 text-xs font-medium text-slate-800 shadow-2xs focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        >
          {navGroups.map((group) => (
            <optgroup key={group.id} label={group.title}>
              {group.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {/* Desktop Vertical Navigation Menu */}
      <nav className="hidden lg:block space-y-6" aria-label="Settings section navigation">
        {navGroups.map((group) => (
          <div key={group.id} className="space-y-1">
            <h3 className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              {group.title}
            </h3>
            <div className="space-y-0.5 mt-1.5">
              {group.items.map((item) => {
                const isActive = activeSection === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelectSection(item.id)}
                    className={`group flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium transition-all text-left cursor-pointer ${
                      isActive
                        ? "bg-brand-50/80 text-brand-700 font-semibold border-l-2 border-brand-600 shadow-2xs"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 border-l-2 border-transparent"
                    }`}
                  >
                    <span className={`${isActive ? "text-brand-600" : "text-slate-400 group-hover:text-slate-600"}`}>
                      {item.icon}
                    </span>
                    <span className="flex-1 truncate">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </div>
  );
}
