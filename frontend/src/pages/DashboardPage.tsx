import { useEffect, useState, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import { useHealth } from "../hooks/useHealth";
import { api } from "../services/api";
import { userFacingError } from "../services/errors";
import type {
  AppView,
  DocumentRecord,
  ConversationSummary,
  TraceAnalyticsResponse,
  PlatformAlertSummary,
} from "../types";
import { PageShell, PageHeader } from "../components/layout";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  StatusBadge,
  Badge,
  ErrorState,
  LoadingState,
} from "../components/ui";
import { DocumentStatusBadge } from "../components/DocumentStatusBadge";
import { formatDate, formatFileSize, getUserDisplayName } from "../utils/format";

type DashboardPageProps = {
  onNavigate: (view: AppView) => void;
};

type AnalyticsPeriod = "24h" | "7d" | "30d";

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function getTimeRangeIso(period: AnalyticsPeriod): string {
  const now = Date.now();
  const hours = period === "24h" ? 24 : period === "7d" ? 24 * 7 : 24 * 30;
  return new Date(now - hours * 3600 * 1000).toISOString();
}

export function DashboardPage({ onNavigate }: DashboardPageProps) {
  const { user, activeWorkspace, isWorkspaceAdmin, canUpload } = useAuth();
  const health = useHealth();

  // State: Documents
  const [documents, setDocuments] = useState<DocumentRecord[] | null>(null);
  const [documentsLoading, setDocumentsLoading] = useState<boolean>(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  // State: Conversations
  const [conversations, setConversations] = useState<ConversationSummary[] | null>(null);
  const [conversationsLoading, setConversationsLoading] = useState<boolean>(true);
  const [conversationsError, setConversationsError] = useState<string | null>(null);

  // State: Workspace Members
  const [memberCount, setMemberCount] = useState<number | null>(null);

  // State: Trace Analytics
  const [period, setPeriod] = useState<AnalyticsPeriod>("7d");
  const [analytics, setAnalytics] = useState<TraceAnalyticsResponse | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState<boolean>(true);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);

  // State: Platform Alerts (Admin only)
  const [openAlerts, setOpenAlerts] = useState<PlatformAlertSummary[] | null>(null);
  const [alertsLoading, setAlertsLoading] = useState<boolean>(false);

  // Fetch Documents
  const fetchDocuments = useCallback(async () => {
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      const data = await api.listDocuments();
      setDocuments(data.documents);
    } catch (err) {
      setDocumentsError(userFacingError(err, "list"));
    } finally {
      setDocumentsLoading(false);
    }
  }, []);

  // Fetch Conversations
  const fetchConversations = useCallback(async () => {
    setConversationsLoading(true);
    setConversationsError(null);
    try {
      const data = await api.listConversations();
      setConversations(data.conversations);
    } catch (err) {
      setConversationsError(userFacingError(err, "list"));
    } finally {
      setConversationsLoading(false);
    }
  }, []);

  // Fetch Members
  const fetchMembers = useCallback(async () => {
    if (!activeWorkspace?.id) return;
    try {
      const data = await api.listWorkspaceMembers(activeWorkspace.id);
      setMemberCount(data.members.length);
    } catch {
      setMemberCount(null);
    }
  }, [activeWorkspace?.id]);

  // Fetch Trace Analytics
  const fetchAnalytics = useCallback(async (selectedPeriod: AnalyticsPeriod) => {
    setAnalyticsLoading(true);
    setAnalyticsError(null);
    try {
      const from_time = getTimeRangeIso(selectedPeriod);
      const data = await api.getTraceAnalytics({
        workspace_id: activeWorkspace?.id,
        from_time,
      });
      setAnalytics(data);
    } catch (err) {
      setAnalyticsError(userFacingError(err, "list"));
    } finally {
      setAnalyticsLoading(false);
    }
  }, [activeWorkspace?.id]);

  // Fetch Alerts (Admin only)
  const fetchAlerts = useCallback(async () => {
    if (!isWorkspaceAdmin) return;
    setAlertsLoading(true);
    try {
      const data = await api.listAlerts({
        workspace_id: activeWorkspace?.id,
        status: "OPEN",
        limit: 10,
      });
      setOpenAlerts(data.items);
    } catch {
      setOpenAlerts(null);
    } finally {
      setAlertsLoading(false);
    }
  }, [activeWorkspace?.id, isWorkspaceAdmin]);

  // Initial load and workspace change handler
  useEffect(() => {
    fetchDocuments();
    fetchConversations();
    fetchMembers();
    fetchAnalytics(period);
    if (isWorkspaceAdmin) {
      fetchAlerts();
    }
  }, [fetchDocuments, fetchConversations, fetchMembers, fetchAnalytics, fetchAlerts, period, isWorkspaceAdmin]);

  // Document status metrics
  const totalDocs = documents?.length ?? 0;
  const readyDocs = documents?.filter((d) => d.status === "COMPLETED").length ?? 0;
  const processingDocs = documents?.filter((d) => d.status === "PROCESSING").length ?? 0;
  const failedDocs = documents?.filter((d) => d.status === "FAILED").length ?? 0;

  // Recent 5 documents sorted by updated_at / created_at descending
  const recentDocuments = documents
    ? [...documents]
        .sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime())
        .slice(0, 5)
    : [];

  // Recent 5 conversations sorted by updated_at descending
  const recentConversations = conversations
    ? [...conversations]
        .sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime())
        .slice(0, 5)
    : [];

  const displayName = getUserDisplayName(user);
  const greeting = getGreeting();
  const workspaceName = activeWorkspace?.name || "your workspace";

  return (
    <PageShell>
      {/* 1. Simplified Workspace Header */}
      <PageHeader
        title={`${greeting}, ${displayName}`}
        description={`Welcome to ${workspaceName}. Here's what's happening in your knowledge workspace.`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => onNavigate("assistant")}
              startIcon={
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
                </svg>
              }
            >
              Ask a question
            </Button>
            {canUpload && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onNavigate("documents")}
                startIcon={
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                }
              >
                Add document
              </Button>
            )}
            {isWorkspaceAdmin && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigate("settings")}
              >
                Manage workspace
              </Button>
            )}
          </div>
        }
      />

      {/* 2. Unified Metric Strip (Cohesive, identical height & style) */}
      <section aria-label="Workspace summary metrics" className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        {/* Metric 1: Documents */}
        <div className="rounded-xl border border-slate-200/80 bg-white p-4 transition-all">
          <div className="text-xs font-medium text-slate-500">Documents</div>
          <div className="mt-1.5 text-2xl font-bold tracking-tight text-slate-900">
            {documentsLoading ? "…" : totalDocs}
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            {documentsLoading
              ? "Checking sources…"
              : totalDocs === 0
              ? "No documents uploaded"
              : `${readyDocs} ready for retrieval`}
          </div>
        </div>

        {/* Metric 2: Conversations */}
        <div className="rounded-xl border border-slate-200/80 bg-white p-4 transition-all">
          <div className="text-xs font-medium text-slate-500">Conversations</div>
          <div className="mt-1.5 text-2xl font-bold tracking-tight text-slate-900">
            {conversationsLoading ? "…" : conversations?.length ?? 0}
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            {conversationsLoading
              ? "Loading chats…"
              : conversations?.length === 0
              ? "No active chats yet"
              : "Saved assistant sessions"}
          </div>
        </div>

        {/* Metric 3: Knowledge Queries */}
        <div className="rounded-xl border border-slate-200/80 bg-white p-4 transition-all">
          <div className="text-xs font-medium text-slate-500">Knowledge Queries</div>
          <div className="mt-1.5 text-2xl font-bold tracking-tight text-slate-900">
            {analyticsLoading ? "…" : analytics?.overview.request_count ?? 0}
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            {analyticsLoading
              ? "Calculating activity…"
              : `Last ${period === "24h" ? "24 hours" : period === "7d" ? "7 days" : "30 days"}`}
          </div>
        </div>

        {/* Metric 4: Workspace Members */}
        <div className="rounded-xl border border-slate-200/80 bg-white p-4 transition-all">
          <div className="text-xs font-medium text-slate-500">Workspace Members</div>
          <div className="mt-1.5 text-2xl font-bold tracking-tight text-slate-900">
            {memberCount === null ? "—" : memberCount}
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">
            {memberCount === null ? "Team size unavailable" : "Active collaborators"}
          </div>
        </div>
      </section>

      {/* 3. Middle Section: Activity (2fr) + Workspace Overview (1fr) */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Left: Knowledge Activity (2/3 width on desktop) */}
        <Card aria-labelledby="activity-heading" className="lg:col-span-2 flex flex-col justify-between">
          <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <CardTitle id="activity-heading">Knowledge Activity</CardTitle>
              <CardDescription>Query volume and response performance</CardDescription>
            </div>
            {/* Period Selector Tabs */}
            <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5" role="tablist" aria-label="Activity time period">
              {(["24h", "7d", "30d"] as const).map((p) => {
                const label = p === "24h" ? "Today" : p === "7d" ? "7 days" : "30 days";
                const isSelected = period === p;
                return (
                  <button
                    key={p}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    onClick={() => setPeriod(p)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                      isSelected
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-600 hover:text-slate-900"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </CardHeader>

          <CardContent className="pt-4 flex-1 flex flex-col justify-center">
            {analyticsLoading ? (
              <LoadingState message="Loading activity metrics…" size="sm" />
            ) : analyticsError ? (
              <ErrorState
                title="Activity metrics unavailable"
                message={analyticsError}
                onRetry={() => fetchAnalytics(period)}
              />
            ) : !analytics || analytics.overview.request_count === 0 ? (
              /* Compact empty state matching panel height */
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <div className="mb-2 flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-400">
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                  </svg>
                </div>
                <h3 className="text-xs font-semibold text-slate-800">No activity yet</h3>
                <p className="mt-1 max-w-sm text-xs text-slate-500 leading-normal">
                  Questions and response performance will appear here as your workspace is used.
                </p>
                <div className="mt-3">
                  <Button variant="secondary" size="sm" onClick={() => onNavigate("assistant")}>
                    Ask a question
                  </Button>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                  <p className="text-xs font-medium text-slate-500">Query Volume</p>
                  <p className="mt-1 text-xl font-bold tracking-tight text-slate-900">
                    {analytics.overview.request_count}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    {analytics.overview.successful_count} successful
                  </p>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                  <p className="text-xs font-medium text-slate-500">Avg Response Latency</p>
                  <p className="mt-1 text-xl font-bold tracking-tight text-slate-900">
                    {analytics.overview.average_latency_ms != null
                      ? `${Math.round(analytics.overview.average_latency_ms)} ms`
                      : "—"}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    p95: {analytics.overview.p95_latency_ms != null ? `${Math.round(analytics.overview.p95_latency_ms)} ms` : "—"}
                  </p>
                </div>

                <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                  <p className="text-xs font-medium text-slate-500">Success Rate</p>
                  <p className="mt-1 text-xl font-bold tracking-tight text-slate-900">
                    {analytics.overview.request_count > 0
                      ? `${Math.round(
                          (analytics.overview.successful_count / analytics.overview.request_count) * 100
                        )}%`
                      : "—"}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Grounded queries
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right: Unified Workspace Overview (One consolidated panel replacing 4 separate cards) */}
        <Card aria-labelledby="workspace-overview-heading" className="flex flex-col justify-between">
          <CardHeader className="border-b border-slate-100 pb-3">
            <CardTitle id="workspace-overview-heading">Workspace Overview</CardTitle>
            <CardDescription>Knowledge base and service status</CardDescription>
          </CardHeader>

          <CardContent className="space-y-4 pt-4">
            {/* Section 1: Knowledge Base Breakdown */}
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-slate-800 mb-2">
                <span>Knowledge Base</span>
                {canUpload && (
                  <button
                    type="button"
                    onClick={() => onNavigate("documents")}
                    className="text-[11px] font-medium text-brand-600 hover:text-brand-700 hover:underline"
                  >
                    Manage →
                  </button>
                )}
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Ready</span>
                  <span className="font-medium text-slate-800">{readyDocs}</span>
                </div>
                {processingDocs > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-amber-700">Processing</span>
                    <span className="font-semibold text-amber-800">{processingDocs}</span>
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <span className={failedDocs > 0 ? "text-rose-600 font-medium" : "text-slate-500"}>
                    Needs attention
                  </span>
                  <span className={failedDocs > 0 ? "font-bold text-rose-700" : "font-medium text-slate-800"}>
                    {failedDocs}
                  </span>
                </div>
              </div>

              {failedDocs > 0 && (
                <div className="mt-2.5 flex items-center justify-between rounded-lg bg-rose-50/80 px-2.5 py-1.5 text-[11px] text-rose-800">
                  <span>{failedDocs} document{failedDocs > 1 ? "s" : ""} failed processing</span>
                  <button
                    type="button"
                    onClick={() => onNavigate("documents")}
                    className="font-semibold underline hover:text-rose-900"
                  >
                    View
                  </button>
                </div>
              )}
            </div>

            <div className="border-t border-slate-100 pt-3">
              {/* Section 2: Platform Status */}
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-800">Platform Status</span>
                <StatusBadge
                  status={health.status === "ok" ? "ok" : health.status === "loading" ? "loading" : "error"}
                  label={health.message}
                  size="sm"
                />
              </div>
            </div>

            {/* Section 3: Operational Alerts Signal (Role-aware) */}
            {isWorkspaceAdmin && (
              <div className="border-t border-slate-100 pt-3">
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="font-semibold text-slate-800">Operational Alerts</span>
                  {openAlerts && openAlerts.length > 0 ? (
                    <Badge variant="danger" size="sm">
                      {openAlerts.length} Open
                    </Badge>
                  ) : null}
                </div>

                {alertsLoading ? (
                  <p className="text-xs text-slate-400">Checking alert rules…</p>
                ) : openAlerts && openAlerts.length > 0 ? (
                  <div className="flex items-center justify-between rounded-lg bg-rose-50/80 px-2.5 py-1.5 text-xs text-rose-900">
                    <span className="truncate">⚠ {openAlerts.length} active alert{openAlerts.length > 1 ? "s" : ""}</span>
                    <button
                      type="button"
                      onClick={() => onNavigate("settings")}
                      className="shrink-0 font-medium text-rose-700 underline hover:text-rose-900"
                    >
                      View in Settings
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 text-xs text-emerald-700">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                    <span>All clear — No active alerts</span>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 4. Lower Section: Balanced Sibling Panels (Recent Documents + Recent Conversations) */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Sibling 1: Recent Documents */}
        <Card aria-labelledby="recent-docs-heading" className="flex flex-col justify-between">
          <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <CardTitle id="recent-docs-heading">Recent Documents</CardTitle>
              <CardDescription>Knowledge sources in this workspace</CardDescription>
            </div>
            <button
              type="button"
              onClick={() => onNavigate("documents")}
              className="text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline"
            >
              View all documents →
            </button>
          </CardHeader>

          <CardContent className="pt-3 flex-1 flex flex-col justify-center">
            {documentsLoading ? (
              <LoadingState message="Loading documents…" size="sm" />
            ) : documentsError ? (
              <ErrorState
                title="Could not load documents"
                message={documentsError}
                onRetry={fetchDocuments}
              />
            ) : recentDocuments.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <p className="text-xs font-semibold text-slate-800">Your knowledge base is empty</p>
                <p className="mt-1 text-xs text-slate-500">
                  Add documents to start asking questions with citations.
                </p>
                {canUpload && (
                  <div className="mt-3">
                    <Button variant="secondary" size="sm" onClick={() => onNavigate("documents")}>
                      Add document
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentDocuments.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center justify-between py-2.5 first:pt-1 last:pb-1"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                        </svg>
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-slate-900">
                          {doc.original_filename || doc.filename}
                        </p>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          {formatFileSize(doc.file_size)} • {formatDate(doc.updated_at || doc.created_at)}
                        </p>
                      </div>
                    </div>

                    <div className="shrink-0">
                      <DocumentStatusBadge status={doc.status} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Sibling 2: Recent Conversations */}
        <Card aria-labelledby="recent-convs-heading" className="flex flex-col justify-between">
          <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3">
            <div>
              <CardTitle id="recent-convs-heading">Recent Conversations</CardTitle>
              <CardDescription>Previous assistant questions and answers</CardDescription>
            </div>
            <button
              type="button"
              onClick={() => onNavigate("assistant")}
              className="text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline"
            >
              Open assistant →
            </button>
          </CardHeader>

          <CardContent className="pt-3 flex-1 flex flex-col justify-center">
            {conversationsLoading ? (
              <LoadingState message="Loading conversations…" size="sm" />
            ) : conversationsError ? (
              <ErrorState
                title="Could not load conversations"
                message={conversationsError}
                onRetry={fetchConversations}
              />
            ) : recentConversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-center">
                <p className="text-xs font-semibold text-slate-800">No conversations yet</p>
                <p className="mt-1 text-xs text-slate-500">
                  Start your first knowledge session with citations.
                </p>
                <div className="mt-3">
                  <Button variant="secondary" size="sm" onClick={() => onNavigate("assistant")}>
                    Ask a question
                  </Button>
                </div>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentConversations.map((conv) => (
                  <button
                    key={conv.id}
                    type="button"
                    onClick={() => onNavigate("assistant")}
                    className="group flex w-full items-center justify-between py-2.5 text-left transition-colors hover:bg-slate-50/70 rounded-lg px-2 -mx-2 first:pt-1 last:pb-1"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 ring-1 ring-brand-200/60">
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 0 1 .865-.501 48.172 48.172 0 0 0 3.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" />
                        </svg>
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-slate-800 group-hover:text-brand-700">
                          {conv.title?.trim() || "Untitled conversation"}
                        </p>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          Updated {formatDate(conv.updated_at || conv.created_at)}
                        </p>
                      </div>
                    </div>

                    <span className="text-slate-400 group-hover:text-slate-600 transition-transform group-hover:translate-x-0.5">
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                      </svg>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}
