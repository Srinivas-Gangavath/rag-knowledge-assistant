export type SettingsSectionId =
  | "overview"
  | "workspace-general"
  | "workspace-members"
  | "workspace-access"
  | "organization-members"
  | "organization-workspaces"
  | "security"
  | "operations"
  | "account";

export type SettingsNavGroup = {
  id: string;
  title: string;
  roleRequired?: "workspace-admin" | "org-admin" | "org-owner";
  items: SettingsNavItem[];
};

export type SettingsNavItem = {
  id: SettingsSectionId;
  label: string;
  description: string;
  path: string;
  roleRequired?: "workspace-admin" | "org-admin" | "org-owner";
  badge?: string;
};
