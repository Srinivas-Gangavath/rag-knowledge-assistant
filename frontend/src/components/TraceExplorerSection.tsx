import { TraceExplorerView } from "./observability/TraceExplorerView";

interface TraceExplorerSectionProps {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
}

export function TraceExplorerSection({ workspaceId, isOrgAdminOrOwner }: TraceExplorerSectionProps) {
  return (
    <TraceExplorerView
      workspaceId={workspaceId}
      isOrgAdminOrOwner={isOrgAdminOrOwner}
    />
  );
}
