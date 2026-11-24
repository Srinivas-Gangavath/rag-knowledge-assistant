import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { AlertRule, AlertRuleCreateRequest } from "../../types";
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
  Modal,
  type BadgeVariant,
} from "../ui";
import { formatAlertType } from "../../utils/format";

type AlertRulesViewProps = {
  workspaceId?: string;
  isOrgAdminOrOwner?: boolean;
};

export function AlertRulesView({
  workspaceId,
}: AlertRulesViewProps) {
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create / Edit Modal State
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [formData, setFormData] = useState<AlertRuleCreateRequest>({
    rule_type: "LATENCY_HIGH",
    metric_name: "total_latency_p95",
    operator: "GT",
    threshold: 3000,
    window_minutes: 15,
    minimum_sample_size: 5,
    severity: "WARNING",
    enabled: true,
    cooldown_minutes: 60,
  });
  const [savingRule, setSavingRule] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function loadRules() {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.listAlertRules(workspaceId || undefined);
      setRules(res.items);
    } catch (err) {
      setError(userFacingError(err, "list"));
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadRules();
  }, [workspaceId]);

  function handleOpenCreate() {
    setEditingRule(null);
    setFormData({
      workspace_id: workspaceId || null,
      rule_type: "LATENCY_HIGH",
      metric_name: "total_latency_p95",
      operator: "GT",
      threshold: 3000,
      window_minutes: 15,
      minimum_sample_size: 5,
      severity: "WARNING",
      enabled: true,
      cooldown_minutes: 60,
    });
    setFormError(null);
    setModalOpen(true);
  }

  function handleOpenEdit(rule: AlertRule) {
    setEditingRule(rule);
    setFormData({
      workspace_id: rule.workspace_id,
      rule_type: rule.rule_type,
      metric_name: rule.metric_name,
      operator: rule.operator,
      threshold: rule.threshold,
      window_minutes: rule.window_minutes,
      minimum_sample_size: rule.minimum_sample_size,
      severity: rule.severity,
      enabled: rule.enabled,
      cooldown_minutes: rule.cooldown_minutes,
    });
    setFormError(null);
    setModalOpen(true);
  }

  // Delete Rule Modal State
  const [pendingDeleteRule, setPendingDeleteRule] = useState<AlertRule | null>(null);
  const [deletingRule, setDeletingRule] = useState(false);

  async function handleToggleRule(rule: AlertRule) {
    try {
      const updated = await api.updateAlertRule(rule.id, {
        enabled: !rule.enabled,
      });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      setError("Failed to toggle rule: " + userFacingError(err));
    }
  }

  async function handleConfirmDelete() {
    if (!pendingDeleteRule) return;
    setDeletingRule(true);
    try {
      await api.deleteAlertRule(pendingDeleteRule.id);
      setRules((prev) => prev.filter((r) => r.id !== pendingDeleteRule.id));
      setPendingDeleteRule(null);
    } catch (err) {
      setError("Failed to delete rule: " + userFacingError(err));
    } finally {
      setDeletingRule(false);
    }
  }

  async function handleFormSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSavingRule(true);
    setFormError(null);
    try {
      if (editingRule) {
        const updated = await api.updateAlertRule(editingRule.id, formData);
        setRules((prev) => prev.map((r) => (r.id === editingRule.id ? updated : r)));
      } else {
        const created = await api.createAlertRule({
          ...formData,
          workspace_id: workspaceId || undefined,
        });
        setRules((prev) => [created, ...prev]);
      }
      setModalOpen(false);
    } catch (err) {
      setFormError(userFacingError(err));
    } finally {
      setSavingRule(false);
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

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/80 pb-3">
        <div>
          <h3 className="text-xs font-bold text-slate-900">Configured Operational Alert Rules</h3>
          <p className="text-[11px] text-slate-500">
            Rules continuously evaluated against query traces and performance distributions.
          </p>
        </div>

        <Button variant="primary" size="sm" onClick={handleOpenCreate}>
          Create Alert Rule
        </Button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800" role="alert">
          {error}
        </div>
      )}

      {/* Rules Table */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Rule Type / Metric</TableHead>
              <TableHead>Condition</TableHead>
              <TableHead className="text-right">Threshold</TableHead>
              <TableHead className="text-right">Window</TableHead>
              <TableHead className="text-right">Min Sample</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && rules.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-slate-400">
                  Loading alert rules...
                </TableCell>
              </TableRow>
            ) : rules.length === 0 ? (
              <TableEmpty colSpan={8} message="No alert rules configured for this scope." />
            ) : (
              rules.map((rule) => (
                <TableRow key={rule.id} className="hover:bg-slate-50/70">
                  <TableCell>
                    <span className="font-semibold text-slate-800 block">
                      {formatAlertType(rule.rule_type)}
                    </span>
                    <span className="font-mono text-[10px] text-slate-500 block">
                      {rule.metric_name}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-slate-700">
                    {rule.operator}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-slate-900">
                    {rule.threshold.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-600">
                    {rule.window_minutes}m
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-600">
                    {rule.minimum_sample_size}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getSeverityBadgeVariant(rule.severity)} size="sm">
                      {rule.severity}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      onClick={() => handleToggleRule(rule)}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                        rule.enabled ? "bg-brand-600" : "bg-slate-200"
                      }`}
                      role="switch"
                      aria-checked={rule.enabled}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                          rule.enabled ? "translate-x-4" : "translate-x-0"
                        }`}
                      />
                    </button>
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-2 text-xs">
                      <button
                        type="button"
                        onClick={() => handleOpenEdit(rule)}
                        className="text-brand-600 hover:text-brand-800 font-semibold hover:underline cursor-pointer"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => setPendingDeleteRule(rule)}
                        className="text-rose-600 hover:text-rose-800 font-semibold hover:underline cursor-pointer"
                      >
                        Delete
                      </button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Delete Rule Confirmation Modal */}
      {pendingDeleteRule && (
        <Modal
          isOpen={Boolean(pendingDeleteRule)}
          onClose={() => setPendingDeleteRule(null)}
          title="Delete Alert Rule"
          description={`Are you sure you want to delete the rule "${formatAlertType(pendingDeleteRule.rule_type)}"? This action will remove automated evaluation for this metric.`}
          size="sm"
          footer={
            <div className="flex items-center justify-end gap-2 w-full">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPendingDeleteRule(null)}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                size="sm"
                isLoading={deletingRule}
                onClick={handleConfirmDelete}
              >
                Delete Rule
              </Button>
            </div>
          }
        >
          <div className="rounded-lg bg-slate-50 p-3 text-xs border border-slate-200">
            <div className="font-semibold text-slate-800">{formatAlertType(pendingDeleteRule.rule_type)}</div>
            <div className="font-mono text-slate-500 mt-1">
              Metric: {pendingDeleteRule.metric_name} {pendingDeleteRule.operator} {pendingDeleteRule.threshold}
            </div>
          </div>
        </Modal>
      )}

      {/* Create / Edit Rule Modal */}
      {modalOpen && (
        <Modal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          title={editingRule ? "Edit Alert Rule" : "Create Alert Rule"}
          description="Configure the performance metric, threshold operator, and observation window."
          size="md"
          footer={
            <div className="flex items-center justify-end gap-2 w-full">
              <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" type="submit" form="alert-rule-form" isLoading={savingRule}>
                {editingRule ? "Save Rule" : "Create Rule"}
              </Button>
            </div>
          }
        >
          <form id="alert-rule-form" onSubmit={handleFormSubmit} className="space-y-4 text-xs">
            {formError && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-rose-800">
                {formError}
              </div>
            )}

            <div>
              <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                Rule Type
              </label>
              <select
                value={formData.rule_type}
                onChange={(e) => setFormData({ ...formData, rule_type: e.target.value })}
                className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="LATENCY_HIGH">Elevated Total Latency</option>
                <option value="RETRIEVAL_SLOW">Slow Retrieval Stage</option>
                <option value="RERANKER_SLOW">Slow Reranking Stage</option>
                <option value="LLM_SLOW">Slow Generation Stage</option>
                <option value="LLM_ERROR_RATE_HIGH">High LLM Error Rate</option>
                <option value="STREAM_TTFT_HIGH">Elevated Time to First Token</option>
                <option value="PROVIDER_FAILURE_SPIKE">Provider Failure Spike</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                  Metric Name
                </label>
                <input
                  type="text"
                  value={formData.metric_name}
                  onChange={(e) => setFormData({ ...formData, metric_name: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none font-mono"
                  required
                />
              </div>

              <div>
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                  Operator
                </label>
                <select
                  value={formData.operator}
                  onChange={(e) => setFormData({ ...formData, operator: e.target.value as "GT" | "GTE" | "LT" | "LTE" | "EQ" })}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none font-mono"
                >
                  <option value="GT">&gt; (Greater Than)</option>
                  <option value="GTE">&gt;= (Greater Than or Equal)</option>
                  <option value="LT">&lt; (Less Than)</option>
                  <option value="LTE">&lt;= (Less Than or Equal)</option>
                  <option value="EQ">= (Equal)</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                  Threshold
                </label>
                <input
                  type="number"
                  value={formData.threshold}
                  onChange={(e) => setFormData({ ...formData, threshold: Number(e.target.value) })}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none font-mono"
                  required
                />
              </div>

              <div>
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                  Window (mins)
                </label>
                <input
                  type="number"
                  value={formData.window_minutes || 15}
                  onChange={(e) => setFormData({ ...formData, window_minutes: Number(e.target.value) })}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none font-mono"
                  min={1}
                />
              </div>

              <div>
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                  Min Sample
                </label>
                <input
                  type="number"
                  value={formData.minimum_sample_size || 5}
                  onChange={(e) => setFormData({ ...formData, minimum_sample_size: Number(e.target.value) })}
                  className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none font-mono"
                  min={1}
                />
              </div>
            </div>

            <div>
              <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider block mb-1">
                Severity Level
              </label>
              <select
                value={formData.severity || "WARNING"}
                onChange={(e) => setFormData({ ...formData, severity: e.target.value as "INFO" | "WARNING" | "ERROR" | "CRITICAL" })}
                className="w-full rounded-lg border border-slate-300 bg-white py-1.5 px-3 text-xs text-slate-800 focus:border-brand-500 focus:outline-none"
              >
                <option value="INFO">Info</option>
                <option value="WARNING">Warning</option>
                <option value="ERROR">Error</option>
                <option value="CRITICAL">Critical</option>
              </select>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
