import { useState } from "react";
import type { UserWorkspace } from "../../types";
import { Tabs, TabList, TabTrigger, TabContent } from "../ui";
import { AuditLogsView, ComplianceVerification } from "../security";

type SecuritySectionProps = {
  activeWorkspace: UserWorkspace | null;
  isOrgAdminOrOwner: boolean;
};

export function SecuritySection({
  activeWorkspace,
  isOrgAdminOrOwner,
}: SecuritySectionProps) {
  const [activeTab, setActiveTab] = useState<"audit-logs" | "compliance">("audit-logs");

  return (
    <div className="space-y-6">
      <Tabs value={activeTab} onValueChange={(val) => setActiveTab(val as "audit-logs" | "compliance")}>
        <TabList>
          <TabTrigger value="audit-logs">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              Audit Logs
            </span>
          </TabTrigger>
          <TabTrigger value="compliance">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
              Compliance & Hash Verification
            </span>
          </TabTrigger>
        </TabList>

        <TabContent value="audit-logs" className="pt-4">
          <AuditLogsView
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
            onNavigateToCompliance={() => setActiveTab("compliance")}
          />
        </TabContent>

        <TabContent value="compliance" className="pt-4">
          <ComplianceVerification
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
          />
        </TabContent>
      </Tabs>
    </div>
  );
}
