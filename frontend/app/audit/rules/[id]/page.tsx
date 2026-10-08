"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, type ApiError } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";
import { SeverityBadge, StatusBadge } from "@/components/RuleBadges";

type Rule = {
  id: string;
  rule_code: string;
  name: string;
  description: string | null;
  domain: string;
  severity: string;
  status: string;
  current_version: number;
  definition: Record<string, unknown>;
  approved_by: string | null;
  approved_at: string | null;
};

type Run = {
  id: string;
  rule_version: number;
  trigger_type: string;
  status: string;
  started_at: string;
  records_checked: number;
  exceptions_created: number;
  warnings: string[];
  error: string | null;
};

type Load =
  | { state: "loading" }
  | { state: "ready"; rule: Rule; runs: Run[] }
  | { state: "error"; message: string };

type Note = { kind: "ok" | "problem"; text: string } | null;

function loadError(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view rules.";
  if (status === 404) return "Rule not found.";
  return `Could not load the rule (HTTP ${status}).`;
}

function actionProblem(status: number, error: ApiError): string {
  const detail = error?.detail;
  if (status === 403 && detail === "MAKER_CHECKER") {
    return "This rule needs approval from someone other than its author.";
  }
  if (status === 403) return "Your role cannot do this.";
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "errors" in detail && Array.isArray(detail.errors)) {
    return detail.errors.join("; ");
  }
  return `The action did not complete (HTTP ${status}).`;
}

export default function RuleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useDevRole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(
    () =>
      Promise.all([
        apiGet<Rule>(`/audit/rules/${id}`, role),
        apiGet<Run[]>(`/audit/rules/${id}/runs`, role),
      ])
        .then(([rule, runs]) =>
          setLoad(
            rule.status === 200 && rule.data
              ? { state: "ready", rule: rule.data, runs: runs.data ?? [] }
              : { state: "error", message: loadError(rule.status) },
          ),
        )
        .catch(() => setLoad({ state: "error", message: "API not reachable. Is the backend running?" })),
    [id, role],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  async function act(action: "activate" | "deactivate" | "run") {
    setBusy(true);
    setNote(null);
    try {
      const r = await apiPost<Run>(`/audit/rules/${id}/${action}`, role);
      if (r.status !== 200) {
        setNote({ kind: "problem", text: actionProblem(r.status, r.error) });
      } else if (action === "run" && r.data) {
        setNote({
          kind: "ok",
          text: `Run ${r.data.status.toLowerCase()}: ${r.data.records_checked} records checked, ` +
            `${r.data.exceptions_created} exceptions created.`,
        });
      } else {
        setNote({ kind: "ok", text: action === "activate" ? "Rule activated." : "Rule deactivated." });
      }
      await reload();
    } catch {
      setNote({ kind: "problem", text: "API not reachable. Is the backend running?" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p>
        <Link href="/audit/rules">&larr; Back to rules</Link>
      </p>

      {load.state === "loading" && <p>Loading...</p>}
      {load.state === "error" && <p>{load.message}</p>}

      {load.state === "ready" && (
        <>
          <h1 style={{ marginBottom: 4 }}>
            {load.rule.rule_code}: {load.rule.name}
          </h1>
          <p>
            <SeverityBadge severity={load.rule.severity} /> <StatusBadge status={load.rule.status} />
          </p>
          {load.rule.description && <p>{load.rule.description}</p>}

          <table cellPadding={4} style={{ marginBottom: 16 }}>
            <tbody>
              <tr>
                <th align="left">Domain</th>
                <td>{load.rule.domain}</td>
              </tr>
              <tr>
                <th align="left">Version</th>
                <td>v{load.rule.current_version}</td>
              </tr>
              {load.rule.approved_by && (
                <tr>
                  <th align="left">Approved by</th>
                  <td>{load.rule.approved_by}</td>
                </tr>
              )}
              {load.rule.approved_at && (
                <tr>
                  <th align="left">Approved at</th>
                  <td>{new Date(load.rule.approved_at).toLocaleString()}</td>
                </tr>
              )}
            </tbody>
          </table>

          <div style={{ marginBottom: 12 }}>
            {(load.rule.status === "DRAFT" || load.rule.status === "INACTIVE") && (
              <button disabled={busy} onClick={() => act("activate")} style={{ marginRight: 8 }}>
                Activate
              </button>
            )}
            {load.rule.status === "ACTIVE" && (
              <>
                <button disabled={busy} onClick={() => act("deactivate")} style={{ marginRight: 8 }}>
                  Deactivate
                </button>
                <button disabled={busy} onClick={() => act("run")}>
                  Run now
                </button>
              </>
            )}
          </div>
          {note && (
            <p role="status" style={{ color: note.kind === "ok" ? "#2e7d32" : "#c62828" }}>
              {note.text}
            </p>
          )}

          <h3>Definition</h3>
          <pre style={{ background: "#f5f5f5", padding: 12, overflowX: "auto", fontSize: 13 }}>
            {JSON.stringify(load.rule.definition, null, 2)}
          </pre>

          <h3>Run history</h3>
          {load.runs.length === 0 ? (
            <p>No runs yet.</p>
          ) : (
            <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th align="left">Started</th>
                  <th align="left">Trigger</th>
                  <th align="left">Status</th>
                  <th align="left">Records checked</th>
                  <th align="left">Exceptions created</th>
                  <th align="left">Warnings</th>
                </tr>
              </thead>
              <tbody>
                {load.runs.map((run) => (
                  <tr key={run.id} style={{ borderTop: "1px solid #ccc" }} title={run.error ?? undefined}>
                    <td>{new Date(run.started_at).toLocaleString()}</td>
                    <td>{run.trigger_type}</td>
                    <td>{run.status}</td>
                    <td>{run.records_checked}</td>
                    <td>{run.exceptions_created}</td>
                    <td>{run.warnings.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
