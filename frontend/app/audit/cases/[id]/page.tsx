"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DEV_USER_ID, apiGet, apiPost, type ApiError } from "@/lib/api";
import { type TimelineEntry, actorLabel, describeEntry } from "@/lib/caseTimeline";
import { label, personLabel, shortId } from "@/lib/format";
import { useDevRole } from "@/components/DevRole";
import { CaseStatusBadge, SeverityBadge } from "@/components/RuleBadges";

type CaseException = {
  id: string;
  rule_code: string | null;
  severity: string;
  entity_type: string;
  entity_id: string;
  created_at: string;
};

type CaseDetail = {
  id: string;
  case_number: string;
  title: string;
  domain: string;
  source: string;
  status: string;
  priority: string;
  department_id: string | null;
  assigned_to: string | null;
  closure_reason: string | null;
  opened_at: string;
  closed_at: string | null;
  allowed_next: string[];
  exceptions: CaseException[];
};

type Comment = { id: string; author_id: string; body: string; created_at: string };

type Load =
  | { state: "loading" }
  | { state: "ready"; detail: CaseDetail; comments: Comment[]; timeline: TimelineEntry[] }
  | { state: "error"; message: string };

type Note = { kind: "ok" | "problem"; text: string } | null;

function loadError(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view cases.";
  if (status === 404) return "Case not found or not visible to your role.";
  return `Could not load the case (HTTP ${status}).`;
}

function actionProblem(status: number, error: ApiError): string {
  const detail = error?.detail;
  const info = detail && typeof detail === "object" && !Array.isArray(detail)
    ? (detail as { code?: string; message?: string; allowed_next?: string[] })
    : {};
  if (status === 403 && info.code === "MANAGER_APPROVAL") {
    return "Only an Audit Manager can do this for a HIGH/CRITICAL case.";
  }
  if (status === 403) return "Your role cannot do this.";
  if (status === 404) return "Case not found or not visible to your role.";
  if (status === 409 || status === 422) {
    if (Array.isArray(detail)) return "Please check what you entered.";   // request validation errors
    const allowed = info.allowed_next?.length ? ` Allowed next: ${info.allowed_next.map(label).join(", ")}.` : "";
    return `${info.message ?? (typeof detail === "string" ? detail : "The action was refused.")}${allowed}`;
  }
  return `The action did not complete (HTTP ${status}).`;
}

const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;

export default function CaseWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useDevRole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const [assignee, setAssignee] = useState("");
  const [reasonFor, setReasonFor] = useState<string | null>(null);   // status waiting for a reason
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");

  const reload = useCallback(
    () =>
      Promise.all([
        apiGet<CaseDetail>(`/audit/cases/${id}`, role),
        apiGet<Comment[]>(`/audit/cases/${id}/comments`, role),
        apiGet<TimelineEntry[]>(`/audit/cases/${id}/timeline`, role),
      ])
        .then(([detail, comments, timeline]) =>
          setLoad(
            detail.status === 200 && detail.data
              ? { state: "ready", detail: detail.data, comments: comments.data ?? [], timeline: timeline.data ?? [] }
              : { state: "error", message: loadError(detail.status) },
          ),
        )
        .catch(() => setLoad({ state: "error", message: "API not reachable. Is the backend running?" })),
    [id, role],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  async function act(path: string, body: unknown, success: string): Promise<boolean> {
    setBusy(true);
    setNote(null);
    try {
      const r = await apiPost(`/audit/cases/${id}/${path}`, role, body);
      const ok = r.status === 200 || r.status === 201;
      setNote(ok ? { kind: "ok", text: success } : { kind: "problem", text: actionProblem(r.status, r.error) });
      await reload();
      return ok;
    } catch {
      setNote({ kind: "problem", text: "API not reachable. Is the backend running?" });
      return false;
    } finally {
      setBusy(false);
    }
  }

  function assign(userId: string) {
    act("assign", { assignee_id: userId.trim() }, "Case assigned.").then((ok) => ok && setAssignee(""));
  }

  function moveTo(status: string) {
    if (status === "NO_ISSUE" && reasonFor !== status) {
      setReasonFor(status);                                   // ask for the reason first
      return;
    }
    act("status", { status, reason: status === reasonFor ? reason : undefined }, `Status changed to ${label(status)}.`)
      .then((ok) => {
        if (ok) {
          setReasonFor(null);
          setReason("");
        }
      });
  }

  function addComment() {
    act("comments", { body: comment }, "Comment added.").then((ok) => ok && setComment(""));
  }

  if (load.state !== "ready") {
    return (
      <div>
        <p><Link href="/audit/cases">&larr; Back to cases</Link></p>
        <p>{load.state === "loading" ? "Loading..." : load.message}</p>
      </div>
    );
  }
  const { detail, comments, timeline } = load;

  return (
    <div>
      <p><Link href="/audit/cases">&larr; Back to cases</Link></p>
      <h1 style={{ marginBottom: 4 }}>{detail.case_number}: {detail.title}</h1>
      <p><SeverityBadge severity={detail.priority} /> <CaseStatusBadge status={detail.status} /></p>

      <div style={box}>
        <table cellPadding={4}>
          <tbody>
            <tr><th align="left">Domain</th><td>{label(detail.domain)}</td></tr>
            <tr><th align="left">Source</th><td>{label(detail.source)}</td></tr>
            <tr><th align="left">Assigned</th><td title={detail.assigned_to ?? undefined}>{personLabel(detail.assigned_to)}</td></tr>
            <tr><th align="left">Department</th><td title={detail.department_id ?? undefined}>{detail.department_id ? shortId(detail.department_id) : "-"}</td></tr>
            <tr><th align="left">Opened</th><td>{new Date(detail.opened_at).toLocaleString()}</td></tr>
            {detail.closed_at && <tr><th align="left">Closed</th><td>{new Date(detail.closed_at).toLocaleString()}</td></tr>}
            {detail.closure_reason && <tr><th align="left">Closure reason</th><td>{detail.closure_reason}</td></tr>}
          </tbody>
        </table>
      </div>

      <div style={box}>
        <h3 style={{ marginTop: 0 }}>Actions</h3>
        <div style={{ marginBottom: 8 }}>
          <button disabled={busy} onClick={() => assign(DEV_USER_ID)} style={{ marginRight: 8 }}>Assign to me</button>
          <input value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="User id" size={38} />{" "}
          <button disabled={busy || !assignee.trim()} onClick={() => assign(assignee)}>Assign</button>
        </div>
        <div>
          {detail.allowed_next.length === 0 && <span>No status changes are possible from here.</span>}
          {detail.allowed_next.map((s) => (
            <button key={s} disabled={busy} onClick={() => moveTo(s)} style={{ marginRight: 8 }}>
              {label(s)}
            </button>
          ))}
        </div>
        {reasonFor && (
          <div style={{ marginTop: 8 }}>
            <label>
              Reason for {label(reasonFor)} (required):
              <br />
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} cols={60} />
            </label>
            <br />
            <button disabled={busy || !reason.trim()} onClick={() => moveTo(reasonFor)}>Confirm</button>{" "}
            <button disabled={busy} onClick={() => { setReasonFor(null); setReason(""); }}>Cancel</button>
          </div>
        )}
        {note && (
          <p role="status" style={{ color: note.kind === "ok" ? "#2e7d32" : "#c62828", marginBottom: 0 }}>{note.text}</p>
        )}
      </div>

      <h3>Linked exceptions</h3>
      {detail.exceptions.length === 0 ? (
        <p>No exceptions linked.</p>
      ) : (
        <table cellPadding={8} style={{ borderCollapse: "collapse", marginBottom: 16 }}>
          <thead>
            <tr>
              <th align="left">Rule</th><th align="left">Severity</th><th align="left">Record type</th>
              <th align="left">Record id</th><th align="left">Created</th>
            </tr>
          </thead>
          <tbody>
            {detail.exceptions.map((e) => (
              <tr key={e.id} style={{ borderTop: "1px solid #ccc" }}>
                <td>{e.rule_code ?? "-"}</td>
                <td><SeverityBadge severity={e.severity} /></td>
                <td>{label(e.entity_type)}</td>
                <td title={e.entity_id}>{shortId(e.entity_id)}</td>
                <td>{new Date(e.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Comments</h3>
      {comments.length === 0 && <p>No comments yet.</p>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {comments.map((c) => (
          <li key={c.id} style={{ borderTop: "1px solid #eee", padding: "6px 0" }}>
            <small title={c.author_id}>{personLabel(c.author_id)} · {new Date(c.created_at).toLocaleString()}</small>
            <div style={{ whiteSpace: "pre-wrap" }}>{c.body}</div>
          </li>
        ))}
      </ul>
      <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} cols={70}
                placeholder="Write a comment" aria-label="New comment" />
      <br />
      <button disabled={busy || !comment.trim()} onClick={addComment} style={{ marginBottom: 16 }}>Add comment</button>

      <h3>Timeline</h3>
      <ol style={{ paddingLeft: 20 }}>
        {timeline.map((t, i) => (
          <li key={i} style={{ marginBottom: 4 }}>
            {describeEntry(t)}{" "}
            <small style={{ opacity: 0.7 }}>— {actorLabel(t.actor_id)}, {new Date(t.created_at).toLocaleString()}</small>
          </li>
        ))}
      </ol>
    </div>
  );
}
