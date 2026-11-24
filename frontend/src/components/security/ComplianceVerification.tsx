import { useState } from "react";
import { api } from "../../services/api";
import { userFacingError } from "../../services/errors";
import type { AuditLogVerifyResponse } from "../../types";
import { Button, Badge, Card, CardHeader, CardTitle, CardDescription, CardContent } from "../ui";
import { formatDate } from "../../utils/format";

type ComplianceVerificationProps = {
  workspaceId?: string;
  isOrgAdminOrOwner: boolean;
};

export function ComplianceVerification({
  workspaceId,
  isOrgAdminOrOwner,
}: ComplianceVerificationProps) {
  const [scope, setScope] = useState<"workspace" | "organization">(
    workspaceId ? "workspace" : "organization"
  );
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<AuditLogVerifyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifiedAt, setVerifiedAt] = useState<string | null>(null);

  async function handleVerify() {
    setIsVerifying(true);
    setError(null);
    try {
      const targetWs = scope === "workspace" ? workspaceId : undefined;
      const res = await api.verifyAuditLogs(targetWs);
      setVerifyResult(res);
      setVerifiedAt(new Date().toISOString());
    } catch (err) {
      setError(userFacingError(err));
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Overview & Trigger Card */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>Tamper-Evident Hash Chain Verification</CardTitle>
                <Badge variant="brand" size="sm">
                  SHA-256 Merkle Proof
                </Badge>
              </div>
              <CardDescription className="mt-1">
                Verify that every historical audit event remains cryptographically immutable and chained without insertion, deletion, or modification.
              </CardDescription>
            </div>

            <div className="flex items-center gap-3">
              {isOrgAdminOrOwner && workspaceId && (
                <div className="flex items-center gap-1.5">
                  <label htmlFor="verify-scope" className="text-xs font-medium text-slate-600">
                    Scope:
                  </label>
                  <select
                    id="verify-scope"
                    value={scope}
                    onChange={(e) => setScope(e.target.value as "workspace" | "organization")}
                    className="rounded-lg border border-slate-300 bg-white py-1.5 px-2.5 text-xs text-slate-700 focus:border-brand-500 focus:outline-none shadow-2xs"
                  >
                    <option value="workspace">Active Workspace</option>
                    <option value="organization">Entire Organization</option>
                  </select>
                </div>
              )}

              <Button
                variant="primary"
                size="sm"
                onClick={handleVerify}
                isLoading={isVerifying}
              >
                {isVerifying ? "Verifying Invariants..." : "Run Cryptographic Verification"}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          {error && (
            <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50/80 p-4 text-xs text-rose-800" role="alert">
              <p className="font-semibold">Verification Request Failed</p>
              <p className="mt-0.5">{error}</p>
            </div>
          )}

          {/* Verification Result Display */}
          {verifyResult ? (
            <div
              className={`rounded-xl border p-5 transition-all ${
                verifyResult.is_valid
                  ? "border-emerald-200 bg-emerald-50/50 text-emerald-900"
                  : "border-rose-200 bg-rose-50/60 text-rose-900"
              }`}
              role="status"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-bold text-sm ${
                      verifyResult.is_valid
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-rose-100 text-rose-700"
                    }`}
                  >
                    {verifyResult.is_valid ? "✓" : "!"}
                  </span>
                  <div>
                    <h4 className="text-sm font-bold">
                      {verifyResult.is_valid
                        ? "Cryptographic Verification Valid"
                        : "Integrity Issue Detected in Audit Chain"}
                    </h4>
                    <p className="text-xs mt-0.5 opacity-90">{verifyResult.message}</p>
                  </div>
                </div>

                {verifiedAt && (
                  <span className="text-[11px] text-slate-500 font-mono shrink-0">
                    Checked at {formatDate(verifiedAt)}
                  </span>
                )}
              </div>

              <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3 border-t border-slate-200/60 pt-4 text-xs">
                <div>
                  <span className="text-slate-500 block text-[11px]">Events Verified</span>
                  <span className="text-base font-bold text-slate-900">
                    {verifyResult.events_verified.toLocaleString()} records
                  </span>
                </div>

                <div>
                  <span className="text-slate-500 block text-[11px]">Audit Chain Status</span>
                  <span
                    className={`font-semibold ${
                      verifyResult.is_valid ? "text-emerald-700" : "text-rose-700"
                    }`}
                  >
                    {verifyResult.is_valid ? "Continuous & Untampered" : "Inconsistency Flagged"}
                  </span>
                </div>

                <div>
                  <span className="text-slate-500 block text-[11px]">Target Scope</span>
                  <span className="font-medium text-slate-800">
                    {scope === "organization" ? "Organization Root" : "Active Workspace"}
                  </span>
                </div>
              </div>

              {verifyResult.error_detail && (
                <div className="mt-4 rounded-lg bg-rose-100/70 border border-rose-200 p-3 text-[11px] font-mono text-rose-900">
                  <p className="font-bold">Failure Diagnostic:</p>
                  <p className="mt-0.5 break-all">{verifyResult.error_detail}</p>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 p-5 text-xs text-slate-600 leading-relaxed">
              <p className="font-semibold text-slate-800 mb-1">Audit Log Hash-Chain Specification</p>
              <p>
                The audit system uses an immutable ledger model where each event payload is hashed with SHA-256 alongside the cryptographic digest of the immediately preceding event. Any row modification or deletion breaks the hash chain invariant and will be flagged immediately during validation.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
