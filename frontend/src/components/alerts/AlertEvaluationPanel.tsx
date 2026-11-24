import { useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { AlertEvaluationResponse } from "../../types";
import { Button, Card, CardHeader, CardTitle, CardDescription, CardContent } from "../ui";
import { formatDate } from "../../utils/format";

type AlertEvaluationPanelProps = {
  workspaceId?: string;
  onEvaluationComplete?: () => void;
};

export function AlertEvaluationPanel({
  workspaceId,
  onEvaluationComplete,
}: AlertEvaluationPanelProps) {
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<AlertEvaluationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluatedAt, setEvaluatedAt] = useState<string | null>(null);

  async function handleEvaluate() {
    setIsEvaluating(true);
    setError(null);
    try {
      const res = await api.evaluateAlerts(workspaceId || undefined);
      setEvalResult(res);
      setEvaluatedAt(new Date().toISOString());
      if (onEvaluationComplete) {
        onEvaluationComplete();
      }
    } catch (err) {
      setError(userFacingError(err));
    } finally {
      setIsEvaluating(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <CardTitle>Manual Alert & Incident Evaluation</CardTitle>
              <CardDescription>
                Trigger an on-demand statistical anomaly evaluation across query latency and stage performance distributions.
              </CardDescription>
            </div>

            <Button
              variant="primary"
              size="sm"
              onClick={handleEvaluate}
              isLoading={isEvaluating}
            >
              {isEvaluating ? "Evaluating Rules..." : "Evaluate Now"}
            </Button>
          </div>
        </CardHeader>

        <CardContent>
          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-3.5 text-xs text-rose-800 mb-4" role="alert">
              {error}
            </div>
          )}

          {evalResult ? (
            <div className="rounded-xl border border-brand-200/80 bg-brand-50/40 p-4 space-y-3 text-xs">
              <div className="flex items-center justify-between border-b border-brand-200/60 pb-2">
                <span className="font-bold text-brand-900">
                  Evaluation Execution Completed
                </span>
                {evaluatedAt && (
                  <span className="text-[11px] text-slate-500 font-mono">
                    Executed at {formatDate(evaluatedAt)}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">
                    Rules Evaluated
                  </span>
                  <span className="text-base font-bold text-slate-900">
                    {evalResult.rules_evaluated}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">
                    Alerts Created
                  </span>
                  <span className={`text-base font-bold ${evalResult.alerts_created > 0 ? "text-rose-600" : "text-slate-900"}`}>
                    {evalResult.alerts_created}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">
                    Alerts Updated
                  </span>
                  <span className="text-base font-bold text-slate-900">
                    {evalResult.alerts_updated}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">
                    Anomalies Detected
                  </span>
                  <span className={`text-base font-bold ${evalResult.anomalies_detected > 0 ? "text-amber-600" : "text-slate-900"}`}>
                    {evalResult.anomalies_detected}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 text-xs text-slate-600">
              <p>
                Evaluation analyzes recent query traces against active threshold rules, measuring latency percentiles, error spikes, and retrieval degradation.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
