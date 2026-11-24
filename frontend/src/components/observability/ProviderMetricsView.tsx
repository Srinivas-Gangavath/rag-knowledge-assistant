import type { ProviderModelStats } from "../../types";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  TableEmpty,
  Badge,
} from "../ui";
import { formatMs } from "../../utils/format";

type ProviderMetricsViewProps = {
  providers: ProviderModelStats[];
  isLoading: boolean;
};

export function ProviderMetricsView({
  providers,
  isLoading,
}: ProviderMetricsViewProps) {
  if (isLoading && providers.length === 0) {
    return (
      <div className="py-12 text-center text-xs text-slate-400">
        Loading provider and model metrics...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between px-1">
        <div>
          <h3 className="text-xs font-bold text-slate-900">AI Provider & Model Execution Metrics</h3>
          <p className="text-[11px] text-slate-500">
            Operational performance, error counts, latency percentiles, and token consumption by underlying model.
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Model Identifier</TableHead>
              <TableHead className="text-right">Requests</TableHead>
              <TableHead className="text-right">Errors</TableHead>
              <TableHead className="text-right">Avg Latency</TableHead>
              <TableHead className="text-right">P95 Latency</TableHead>
              <TableHead className="text-right">Input Tokens</TableHead>
              <TableHead className="text-right">Output Tokens</TableHead>
              <TableHead className="text-right">Total Tokens</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {providers.length === 0 ? (
              <TableEmpty
                colSpan={9}
                message="No AI model execution telemetry recorded for the active filter window."
              />
            ) : (
              providers.map((item, idx) => (
                <TableRow key={`${item.provider}-${item.model}-${idx}`} className="hover:bg-slate-50/70">
                  <TableCell className="font-semibold text-slate-800">
                    <span className="capitalize">{item.provider}</span>
                  </TableCell>
                  <TableCell className="font-mono text-slate-800 text-[11px]">
                    {item.model}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-700">
                    {item.request_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {item.error_count > 0 ? (
                      <Badge variant="danger" size="sm">
                        {item.error_count.toLocaleString()}
                      </Badge>
                    ) : (
                      <span className="text-slate-400">0</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono font-medium text-slate-800">
                    {formatMs(item.average_latency_ms)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-700">
                    {formatMs(item.p95_latency_ms)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-600">
                    {item.token_usage_available ? item.input_token_count.toLocaleString() : "N/A"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-600">
                    {item.token_usage_available ? item.output_token_count.toLocaleString() : "N/A"}
                  </TableCell>
                  <TableCell className="text-right font-mono font-bold text-slate-900">
                    {item.token_usage_available ? item.total_token_count.toLocaleString() : "N/A"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
