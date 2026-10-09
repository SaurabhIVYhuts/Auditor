"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost, devUserId, type ApiError } from "@/lib/api";
import { AUDIT_TEAM, type Action, isActionOverdue } from "@/lib/actions";
import { UNREACHABLE, actionProblem, errorInfo } from "@/lib/apiErrors";
import { type TimelineEntry } from "@/lib/caseTimeline";
import { personLabel } from "@/lib/format";
import { useStep } from "@/lib/useStep";
import { useDevRole } from "@/components/DevRole";
import { EvidenceSection } from "@/components/EvidenceSection";
import { ActionStatusBadge } from "@/components/RuleBadges";
import { StepNote } from "@/components/StepNote";
import { Timeline } from "@/components/Timeline";

type Load =
  | { state: "loading" }
  | { state: "ready"; action: Action; timeline: TimelineEntry[] }
  | { state: "error"; message: string };

const NOT_FOUND = "Action not found or not visible to your role.";
const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;
const overdueStyle = { color: "#c62828", fontWeight: 600 } as const;

function loadError(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view corrective actions.";
  if (status === 404) return NOT_FOUND;
  return `Could not load the action (HTTP ${status}).`;
}

function stepProblem(status: number, error: ApiError): string {
  const code = errorInfo(error).code;
  if (status === 403 && code === "MAKER_CHECKER") return "You own this action - someone else must verify it.";
  if (status === 403 && code === "NOT_ALLOWED") return "Only the action owner can do this.";
  return actionProblem(status, error, NOT_FOUND);        // 422 evidence required, 403 MANAGER_APPROVAL, ...
}

export default function ActionPage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useDevRole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [open, setOpen] = useState<"verify" | "return" | null>(null);
  const [text, setText] = useState("");

  const reload = useCallback(
    () =>
      Promise.all([
        apiGet<Action>(`/audit/actions/${id}`, role),
        apiGet<TimelineEntry[]>(`/audit/actions/${id}/timeline`, role),
      ])
        .then(([a, timeline]) =>
          setLoad(a.status === 200 && a.data
            ? { state: "ready", action: a.data, timeline: timeline.data ?? [] }
            : { state: "error", message: loadError(a.status) }),
        )
        .catch(() => setLoad({ state: "error", message: UNREACHABLE })),
    [id, role],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  const { busy, note, run } = useStep(stepProblem, reload);

  async function step(path: string, body: unknown, success: string) {
    if (await run(() => apiPost(`/audit/actions/${id}/${path}`, role, body), success)) {
      setOpen(null);
      setText("");
    }
  }

  if (load.state !== "ready") {
    return (
      <div>
        <p><Link href="/audit/actions">&larr; Back to my actions</Link></p>
        <p>{load.state === "loading" ? "Loading..." : load.message}</p>
      </div>
    );
  }
  const { action: a, timeline } = load;
  const next = new Set(a.allowed_next);
  const ownerSteps = a.owner_user_id === devUserId() || role === "OWN";     // the server checks the owner
  const teamSteps = AUDIT_TEAM.has(role);
  const overdue = isActionOverdue(a);

  return (
    <div>
      <p>
        <Link href="/audit/actions">&larr; Back to my actions</Link>
        {" · "}<Link href={`/audit/findings/${a.finding_id}`}>Finding {a.finding_number}</Link>
        {" · "}<Link href={`/audit/cases/${a.case_id}`}>Case {a.case_number}</Link>
      </p>
      <h1 style={{ marginBottom: 4 }}>{a.action_number}</h1>
      <p><ActionStatusBadge status={a.status} /></p>

      <div style={box}>
        <p style={{ whiteSpace: "pre-wrap", marginTop: 0 }}>{a.description}</p>
        <table cellPadding={4}>
          <tbody>
            <tr><th align="left">Owner</th><td title={a.owner_user_id}>{personLabel(a.owner_user_id)}</td></tr>
            <tr>
              <th align="left">Due date</th>
              <td style={overdue ? overdueStyle : undefined}>{a.due_date}{overdue && " (overdue)"}</td>
            </tr>
            {a.submitted_at && <tr><th align="left">Submitted</th><td>{new Date(a.submitted_at).toLocaleString()}</td></tr>}
            {a.status === "RETURNED" && a.return_note && (
              <tr><th align="left">Returned because</th><td style={{ color: "#e65100" }}>{a.return_note}</td></tr>
            )}
            {a.verified_at && (
              <tr>
                <th align="left">Verified</th>
                <td>
                  <span title={a.verified_by ?? undefined}>{personLabel(a.verified_by)}</span>,{" "}
                  {new Date(a.verified_at).toLocaleString()}
                  {a.verification_note && <div>{a.verification_note}</div>}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {ownerSteps && next.has("IN_PROGRESS") && (
          <button disabled={busy} onClick={() => step("start", undefined, "Work started.")}>
            {a.status === "RETURNED" ? "Start again" : "Start"}
          </button>
        )}
        {ownerSteps && next.has("SUBMITTED") && (
          <button disabled={busy} onClick={() => step("submit", undefined, "Submitted for verification.")}>
            Submit for verification
          </button>
        )}
        {teamSteps && next.has("VERIFIED") && (
          <button disabled={busy} onClick={() => { setOpen(open === "verify" ? null : "verify"); setText(""); }}>Verify</button>
        )}
        {teamSteps && next.has("RETURNED") && (
          <button disabled={busy} onClick={() => { setOpen(open === "return" ? null : "return"); setText(""); }}>Return</button>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 8 }}>
          <label>
            {open === "verify" ? "Verification note (optional):" : "What is still missing (required):"}
            <br />
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} cols={60} />
          </label>
          <br />
          <button
            disabled={busy || (open === "return" && !text.trim())}
            onClick={() => open === "verify"
              ? step("verify", { note: text.trim() || null }, "Action verified.")
              : step("return", { note: text }, "Returned to the owner.")}
          >
            {open === "verify" ? "Verify action" : "Return to owner"}
          </button>
        </div>
      )}
      <StepNote note={note} />

      <EvidenceSection listPath={`/audit/actions/${a.id}`} listField="evidence" uploadPath={`/audit/actions/${a.id}/evidence`} />

      <h3>Timeline</h3>
      <Timeline entries={timeline} />
    </div>
  );
}
