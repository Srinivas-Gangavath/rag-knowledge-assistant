import { AuditLogsView } from "./security/AuditLogsView";

interface AuditLogsSectionProps {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
}

export function AuditLogsSection({ workspaceId, isOrgAdminOrOwner }: AuditLogsSectionProps) {
  return (
    <AuditLogsView
      workspaceId={workspaceId}
      isOrgAdminOrOwner={isOrgAdminOrOwner}
    />
  );
}
