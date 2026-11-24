import { AlertsCenterView } from "./alerts/AlertsCenterView";

interface AlertsSectionProps {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
}

export function AlertsSection({ workspaceId, isOrgAdminOrOwner }: AlertsSectionProps) {
  return (
    <AlertsCenterView
      workspaceId={workspaceId}
      isOrgAdminOrOwner={isOrgAdminOrOwner}
    />
  );
}
