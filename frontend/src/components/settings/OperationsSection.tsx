import { useState } from "react";
import type { UserWorkspace } from "../../types";
import { Tabs, TabList, TabTrigger, TabContent } from "../ui";
import {
  ObservabilityOverview,
  TraceExplorerView,
  SlowQueriesView,
} from "../observability";
import { AlertsCenterView } from "../alerts";
import { RetentionManagementView } from "../retention";

type OperationsSectionProps = {
  activeWorkspace: UserWorkspace | null;
  isOrgAdminOrOwner: boolean;
};

type OperationsTab = "performance" | "traces" | "slow-queries" | "alerts" | "retention";

export function OperationsSection({
  activeWorkspace,
  isOrgAdminOrOwner,
}: OperationsSectionProps) {
  const [activeTab, setActiveTab] = useState<OperationsTab>("performance");
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);

  function handleSelectTraceFromExternal(traceId: string) {
    setSelectedTraceId(traceId);
    setActiveTab("traces");
  }

  return (
    <div className="space-y-6">
      <Tabs value={activeTab} onValueChange={(val) => setActiveTab(val as OperationsTab)}>
        <TabList>
          <TabTrigger value="performance">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Performance & Latency
            </span>
          </TabTrigger>

          <TabTrigger value="traces">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              Trace Explorer
            </span>
          </TabTrigger>

          <TabTrigger value="slow-queries">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Slow Queries
            </span>
          </TabTrigger>

          <TabTrigger value="alerts">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              Alerts & Incidents
            </span>
          </TabTrigger>

          <TabTrigger value="retention">
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Telemetry Retention
            </span>
          </TabTrigger>
        </TabList>

        <TabContent value="performance" className="pt-4">
          <ObservabilityOverview
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
          />
        </TabContent>

        <TabContent value="traces" className="pt-4">
          <TraceExplorerView
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
            selectedTraceIdFromExternal={selectedTraceId}
            onClearExternalTraceId={() => setSelectedTraceId(null)}
          />
        </TabContent>

        <TabContent value="slow-queries" className="pt-4">
          <SlowQueriesView
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
            onSelectTrace={handleSelectTraceFromExternal}
          />
        </TabContent>

        <TabContent value="alerts" className="pt-4">
          <AlertsCenterView
            workspaceId={activeWorkspace?.id}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
            onNavigateToTrace={handleSelectTraceFromExternal}
          />
        </TabContent>

        <TabContent value="retention" className="pt-4">
          <RetentionManagementView
            isOrgAdminOrOwner={isOrgAdminOrOwner}
          />
        </TabContent>
      </Tabs>
    </div>
  );
}
