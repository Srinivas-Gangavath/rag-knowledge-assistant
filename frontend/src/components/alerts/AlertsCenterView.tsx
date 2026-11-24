import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { PlatformAlertDetail, PlatformAlertSummary } from "../../types";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
  Badge,
  Button,
  Tabs,
  TabList,
  TabTrigger,
  TabContent,
  type BadgeVariant,
} from "../ui";
import { formatAlertType, formatDate } from "../../utils/format";
import { AlertDetailsModal } from "./AlertDetailsModal";
import { AlertRulesView } from "./AlertRulesView";
import { AlertEvaluationPanel } from "./AlertEvaluationPanel";

type AlertsCenterViewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
  onNavigateToTrace?: (traceId: string) => void;
};

export function AlertsCenterView({
  workspaceId,
  isOrgAdminOrOwner,
  onNavigateToTrace,
}: AlertsCenterViewProps) {
  const [activeTab, setActiveTab] = useState("incidents");

  // Alerts List State
  const [alerts, setAlerts] = useState<PlatformAlertSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(15);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [alertTypeFilter, setAlertTypeFilter] = useState("");

  // Modal / Detail State
  const [selectedAlertDetail, setSelectedAlertDetail] = useState<PlatformAlertDetail | null>(null);

  async function loadAlerts(targetOffset: number) {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.listAlerts({
        workspace_id: workspaceId || undefined,
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        alert_type: alertTypeFilter || undefined,
        limit,
        offset: targetOffset,
      });
      setAlerts(res.items);
      setTotal(res.total);
      setOffset(res.offset);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadAlerts(0);
  }, [workspaceId, severityFilter, statusFilter, alertTypeFilter]);

  async function handleSelectAlert(alertId: string) {
    try {
      const detail = await api.getAlertDetail(alertId);
      setSelectedAlertDetail(detail);
    } catch (err) {
      alert("Failed to load alert details: " + userFacingError(err));
    }
  }

  async function handleAcknowledge(alertId: string) {
    try {
      const updated = await api.acknowledgeAlert(alertId);
      setAlerts((prev) => prev.map((a) => (a.id === alertId ? updated : a)));
      if (selectedAlertDetail && selectedAlertDetail.id === alertId) {
        setSelectedAlertDetail({ ...selectedAlertDetail, ...updated });
      }
    } catch (err) {
      alert("Failed to acknowledge alert: " + userFacingError(err));
    }
  }

  async function handleResolve(alertId: string, reason?: string) {
    try {
      const updated = await api.resolveAlert(alertId, reason);
      setAlerts((prev) => prev.map((a) => (a.id === alertId ? updated : a)));
      if (selectedAlertDetail && selectedAlertDetail.id === alertId) {
        setSelectedAlertDetail({ ...selectedAlertDetail, ...updated });
      }
    } catch (err) {
      alert("Failed to resolve alert: " + userFacingError(err));
    }
  }

  function getSeverityBadgeVariant(sev: string): BadgeVariant {
    switch (sev.toUpperCase()) {
      case "CRITICAL":
      case "ERROR":
        return "danger";
      case "WARNING":
        return "warning";
      case "INFO":
        return "info";
      default:
        return "neutral";
    }
  }

  function getStatusBadgeVariant(status: string): BadgeVariant {
    switch (status.toUpperCase()) {
      case "OPEN":
        return "danger";
      case "ACKNOWLEDGED":
        return "warning";
      case "RESOLVED":
        return "success";
      default:
        return "neutral";
    }
  }

  // Summary counts
  const openCount = alerts.filter((a) => a.status === "OPEN").length;
  const criticalCount = alerts.filter(
    (a) => (a.severity === "CRITICAL" || a.severity === "ERROR") && a.status !== "RESOLVED"
  ).length;
  const warningCount = alerts.filter(
    (a) => a.severity === "WARNING" && a.status !== "RESOLVED"
  ).length;

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="space-y-5">
      {/* Top Header & Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Alerts & Incident Monitoring</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Operational conditions requiring administrative attention and automated health diagnostics.
          </p>
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => loadAlerts(offset)}
          isLoading={isLoading}
        >
          Refresh Alerts
        </Button>
      </div>

      {/* Summary Metric Strip */}
      <div className="grid grid-cols-3 gap-3 rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Open Incidents
          </span>
          <span className={`text-xl font-bold ${openCount > 0 ? "text-rose-600" : "text-slate-900"}`}>
            {openCount}
          </span>
        </div>

        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Critical Alerts
          </span>
          <span className={`text-xl font-bold ${criticalCount > 0 ? "text-rose-600" : "text-slate-900"}`}>
            {criticalCount}
          </span>
        </div>

        <div>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
            Warnings
          </span>
          <span className={`text-xl font-bold ${warningCount > 0 ? "text-amber-600" : "text-slate-900"}`}>
            {warningCount}
          </span>
        </div>
      </div>

      {/* Subsections Navigation */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabList>
          <TabTrigger value="incidents">Active & Historical Incidents</TabTrigger>
          <TabTrigger value="rules">Alert Rules Management</TabTrigger>
          <TabTrigger value="evaluation">Diagnostics & Evaluation</TabTrigger>
        </TabList>

        {/* Tab 1: Incidents List */}
        <TabContent value="incidents" className="space-y-4">
          {/* Error Feedback */}
          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
              {error}
            </div>
          )}

          {/* Filters Toolbar */}
          <div className="rounded-xl border border-slate-200/90 bg-slate-50/60 p-3 flex flex-wrap items-center gap-2.5 text-xs text-slate-700">
            <div className="flex items-center gap-1">
              <label htmlFor="alert-severity" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Severity:
              </label>
              <select
                id="alert-severity"
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="">All Severities</option>
                <option value="CRITICAL">Critical</option>
                <option value="ERROR">Error</option>
                <option value="WARNING">Warning</option>
                <option value="INFO">Info</option>
              </select>
            </div>

            <div className="flex items-center gap-1">
              <label htmlFor="alert-status" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Status:
              </label>
              <select
                id="alert-status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="">All Statuses</option>
                <option value="OPEN">Open</option>
                <option value="ACKNOWLEDGED">Acknowledged</option>
                <option value="RESOLVED">Resolved</option>
              </select>
            </div>

            <div className="flex items-center gap-1">
              <label htmlFor="alert-type" className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                Alert Type:
              </label>
              <select
                id="alert-type"
                value={alertTypeFilter}
                onChange={(e) => setAlertTypeFilter(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white py-1 px-2 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="">All Types</option>
                <option value="LATENCY_HIGH">Elevated Latency</option>
                <option value="RETRIEVAL_SLOW">Slow Retrieval</option>
                <option value="RERANKER_SLOW">Slow Reranking</option>
                <option value="LLM_SLOW">Slow LLM</option>
                <option value="LLM_ERROR_RATE_HIGH">High Error Rate</option>
                <option value="STREAM_TTFT_HIGH">High TTFT</option>
                <option value="ANOMALY_DETECTED">Statistical Anomaly</option>
              </select>
            </div>
          </div>

          {/* Alerts Table */}
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-28">Severity</TableHead>
                  <TableHead>Alert / Issue</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Metric Observed</TableHead>
                  <TableHead className="w-40">Detected</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading && alerts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-8 text-center text-slate-400">
                      Loading alerts...
                    </TableCell>
                  </TableRow>
                ) : alerts.length === 0 ? (
                  <TableEmpty
                    colSpan={6}
                    message={
                      severityFilter || statusFilter !== "OPEN" || alertTypeFilter
                        ? "No operational alerts match the selected filter criteria."
                        : "No active alerts."
                    }
                  />
                ) : (
                  alerts.map((item) => (
                    <TableRow key={item.id} className="hover:bg-slate-50/70">
                      <TableCell>
                        <Badge variant={getSeverityBadgeVariant(item.severity)} size="sm">
                          {item.severity}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className="font-semibold text-slate-900 block" title={item.title}>
                          {item.title || formatAlertType(item.alert_type)}
                        </span>
                        <span className="text-[11px] text-slate-500 line-clamp-1">
                          {item.description}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant={getStatusBadgeVariant(item.status)} size="sm">
                          {item.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-slate-700 text-[11px]">
                        {item.metric_value !== null ? (
                          <span>
                            {item.metric_value.toLocaleString()}{" "}
                            {item.threshold_value !== null ? `(threshold: ${item.threshold_value})` : ""}
                          </span>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-[11px] text-slate-500">
                        {formatDate(item.detected_at)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-2 text-xs">
                          {item.status === "OPEN" && (
                            <button
                              type="button"
                              onClick={() => handleAcknowledge(item.id)}
                              className="text-amber-600 hover:text-amber-800 font-semibold hover:underline cursor-pointer"
                            >
                              Ack
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => handleSelectAlert(item.id)}
                            className="text-brand-600 hover:text-brand-800 font-semibold hover:underline cursor-pointer"
                          >
                            Details →
                          </button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs text-slate-500 px-1">
            <span>
              Showing page <span className="font-semibold text-slate-800">{currentPage}</span> of{" "}
              <span className="font-semibold text-slate-800">{totalPages}</span> ({total} alerts)
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => loadAlerts(Math.max(0, offset - limit))}
                disabled={offset === 0 || isLoading}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => loadAlerts(offset + limit)}
                disabled={offset + limit >= total || isLoading}
              >
                Next
              </Button>
            </div>
          </div>
        </TabContent>

        {/* Tab 2: Rules */}
        <TabContent value="rules">
          <AlertRulesView
            workspaceId={workspaceId}
            isOrgAdminOrOwner={isOrgAdminOrOwner}
          />
        </TabContent>

        {/* Tab 3: Evaluation */}
        <TabContent value="evaluation">
          <AlertEvaluationPanel
            workspaceId={workspaceId}
            onEvaluationComplete={() => loadAlerts(0)}
          />
        </TabContent>
      </Tabs>

      {/* Alert Details Modal */}
      <AlertDetailsModal
        alert={selectedAlertDetail}
        onClose={() => setSelectedAlertDetail(null)}
        onAcknowledge={handleAcknowledge}
        onResolve={handleResolve}
        onNavigateToTrace={onNavigateToTrace}
      />
    </div>
  );
}
