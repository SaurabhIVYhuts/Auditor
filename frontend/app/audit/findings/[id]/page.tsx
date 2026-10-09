"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DEV_USERS, apiGet, apiPost, apiPut, type ApiError } from "@/lib/api";
import { UNREACHABLE, actionProblem, errorInfo } from "@/lib/apiErrors";
import { type TimelineEntry } from "@/lib/caseTimeline";
import { type Finding, RISK_LEVELS, isOverdue } from "@/lib/findings";
import { label, personLabel } from "@/lib/format";
import { useStep } from "@/lib/useStep";
import { ActionsSection } from "@/components/ActionsSection";
import { useDevRole } from "@/components/DevRole";
import { EvidenceSection } from "@/components/EvidenceSection";
import { FindingStatusBadge, SeverityBadge } from "@/components/RuleBadges";
import { StepNote } from "@/components/StepNote";
import { Timeline } from "@/components/Timeline";

type Load =
  | { state: "loading" }
  | { state: "ready"; finding: Finding; timeline: TimelineEntry[] }
  | { state: "error"; message: string };

const NOT_FOUND = "Finding not found or not visible to your role.";
const TEXT_FIELDS = ["condition", "criteria", "cause", "effect", "recommendation"] as const;
const EDITABLE = [...TEXT_FIELDS, "risk_level", "financial_impact"] as const;
type Field = (typeof EDITABLE)[number];

const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;
const problemColour = "#c62828";

function loadError(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view findings.";
  if (status === 404) return NOT_FOUND;
  return `Could not load the finding (HTTP ${status}).`;
}

function findingProblem(status: number, error: ApiError): string {
  const info = errorInfo(error);
  if (status === 403 && info.code === "MAKER_CHECKER") {
    return "You wrote or submitted this finding - another Audit Manager must confirm it.";
  }
  if (status === 422 && info.missing?.length) return `Please fill in first: ${info.missing.map(label).join(", ")}.`;
  return actionProblem(status, error, NOT_FOUND);
}

function rupees(value: string | null): string {
  return value === null ? "-" : `Rs ${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

export default function FindingPage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useDevRole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [version, setVersion] = useState(0);        // bumped on every reload: resets the editor

  const reload = useCallback(
    () =>
      Promise.all([
        apiGet<Finding>(`/audit/findings/${id}`, role),
        apiGet<TimelineEntry[]>(`/audit/findings/${id}/timeline`, role),
      ])
        .then(([f, timeline]) => {
          if (f.status !== 200 || !f.data) {
            setLoad({ state: "error", message: loadError(f.status) });
            return;
          }
          setLoad({ state: "ready", finding: f.data, timeline: timeline.data ?? [] });
          setVersion((v) => v + 1);
        })
        .catch(() => setLoad({ state: "error", message: UNREACHABLE })),
    [id, role],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  const { busy, note, run } = useStep(findingProblem, reload);

  /** Run one step (PUT or POST); returns true if it worked. */
  function act(method: "POST" | "PUT", path: string, body: unknown, success: string): Promise<boolean> {
    return run(() => method === "POST" ? apiPost(`/audit/findings/${id}${path}`, role, body)
      : apiPut(`/audit/findings/${id}`, role, body), success);
  }

  if (load.state !== "ready") {
    return (
      <div>
        <p><Link href="/audit/findings">&larr; Back to findings</Link></p>
        <p>{load.state === "loading" ? "Loading..." : load.message}</p>
      </div>
    );
  }
  const { finding: f, timeline } = load;

  return (
    <div>
      <p>
        <Link href="/audit/findings">&larr; Back to findings</Link>
        {" · "}
        <Link href={`/audit/cases/${f.case_id}`}>Case {f.case_number}</Link>
      </p>
      <h1 style={{ marginBottom: 4 }}>{f.finding_number}: {f.title}</h1>
      <p>
        {f.risk_level && <SeverityBadge severity={f.risk_level} />} <FindingStatusBadge status={f.status} />
      </p>

      <Review key={`review-${version}`} finding={f} busy={busy} act={act} />
      <StepNote note={note} />

      {(f.confirmed_at || f.dismiss_reason) && (
        <div style={box}>
          <table cellPadding={4}>
            <tbody>
              {f.confirmed_at && (
                <>
                  <tr><th align="left">Owner</th><td title={f.owner_user_id ?? undefined}>{personLabel(f.owner_user_id)}</td></tr>
                  <tr>
                    <th align="left">Due date</th>
                    <td style={isOverdue(f) ? { color: problemColour, fontWeight: 600 } : undefined}>
                      {f.due_date ?? "-"}{isOverdue(f) && " (past due)"}
                    </td>
                  </tr>
                  <tr>
                    <th align="left">Confirmed</th>
                    <td>
                      <span title={f.confirmed_by ?? undefined}>{personLabel(f.confirmed_by)}</span>,{" "}
                      {new Date(f.confirmed_at).toLocaleString()}
                    </td>
                  </tr>
                </>
              )}
              {f.dismiss_reason && <tr><th align="left">Dismissed because</th><td>{f.dismiss_reason}</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      <Editor key={`editor-${version}`} finding={f} busy={busy} act={act} />

      <EvidenceSection
        listPath={`/audit/findings/${f.id}`}
        listField="evidence"
        uploadPath={`/audit/findings/${f.id}/evidence`}
        linkListPath={`/audit/cases/${f.case_id}/evidence`}
        linkPath={`/audit/findings/${f.id}/evidence-links`}
      />

      <ActionsSection finding={f} onChanged={reload} />

      <h3>Timeline</h3>
      <Timeline entries={timeline} />
    </div>
  );
}

type Act = (method: "POST" | "PUT", path: string, body: unknown, success: string) => Promise<boolean>;

/** The structured fields: editable while DRAFT (Save sends only what changed), read-only after. */
function Editor({ finding, busy, act }: { finding: Finding; busy: boolean; act: Act }) {
  const initial = Object.fromEntries(EDITABLE.map((k) => [k, finding[k] ?? ""])) as Record<Field, string>;
  const [form, setForm] = useState(initial);
  const editable = finding.status === "DRAFT";
  const changed = EDITABLE.filter((k) => form[k].trim() !== initial[k].trim());

  function save() {
    const body = Object.fromEntries(changed.map((k) => [k, form[k].trim() === "" ? null : form[k].trim()]));
    act("PUT", "", body, "Finding saved.");
  }

  const set = (k: Field) => (value: string) => setForm((f) => ({ ...f, [k]: value }));

  return (
    <div style={box}>
      <h3 style={{ marginTop: 0 }}>Finding details{!editable && <small style={{ fontWeight: 400 }}> (read-only after submission)</small>}</h3>
      {TEXT_FIELDS.map((k) => (
        <div key={k} style={{ marginBottom: 8 }}>
          <strong>{label(k)}</strong>
          {editable ? (
            <textarea value={form[k]} onChange={(e) => set(k)(e.target.value)} rows={3}
                      style={{ display: "block", width: "100%", maxWidth: 700 }} aria-label={label(k)} />
          ) : (
            <div style={{ whiteSpace: "pre-wrap" }}>{finding[k] || "-"}</div>
          )}
        </div>
      ))}
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 8 }}>
        <label>
          <strong>Risk</strong>{" "}
          {editable ? (
            <select value={form.risk_level} onChange={(e) => set("risk_level")(e.target.value)}>
              <option value="">Not set</option>
              {RISK_LEVELS.map((r) => <option key={r} value={r}>{label(r)}</option>)}
            </select>
          ) : (finding.risk_level ? label(finding.risk_level) : "-")}
        </label>
        <label>
          <strong>Financial impact</strong>{" "}
          {editable ? (
            <>Rs <input type="number" min={0} step="0.01" value={form.financial_impact}
                        onChange={(e) => set("financial_impact")(e.target.value)} style={{ width: 140 }} /></>
          ) : rupees(finding.financial_impact)}
        </label>
      </div>
      {editable && (
        <button disabled={busy || changed.length === 0} onClick={save}>
          Save{changed.length ? ` (${changed.length} change${changed.length === 1 ? "" : "s"})` : ""}
        </button>
      )}
    </div>
  );
}

/** Submit (DRAFT) or Confirm / Return / Dismiss (UNDER_REVIEW), from the finding's allowed_next. */
function Review({ finding, busy, act }: { finding: Finding; busy: boolean; act: Act }) {
  const next = new Set(finding.allowed_next);
  const [open, setOpen] = useState<"confirm" | "return" | "dismiss" | null>(null);
  const [owner, setOwner] = useState(finding.owner_user_id ?? DEV_USERS[0].id);
  const [due, setDue] = useState(finding.due_date ?? "");
  const [text, setText] = useState("");
  const canSubmit = finding.status === "DRAFT" && next.has("UNDER_REVIEW");
  const reviewing = finding.status === "UNDER_REVIEW";

  if (!canSubmit && !reviewing) return null;
  const owners = DEV_USERS.some((u) => u.id === owner) ? DEV_USERS : [...DEV_USERS, { id: owner, name: personLabel(owner) }];

  function choose(which: typeof open) {
    setOpen(open === which ? null : which);
    setText("");
  }

  return (
    <div style={box}>
      <h3 style={{ marginTop: 0 }}>{canSubmit ? "Ready for review?" : "Review"}</h3>
      {canSubmit && (
        <button disabled={busy} onClick={() => act("POST", "/submit", undefined, "Submitted for review.")}>
          Submit for review
        </button>
      )}
      {reviewing && (
        <div style={{ display: "flex", gap: 8 }}>
          {next.has("CONFIRMED") && <button disabled={busy} onClick={() => choose("confirm")}>Confirm</button>}
          {next.has("DRAFT") && <button disabled={busy} onClick={() => choose("return")}>Return for changes</button>}
          {next.has("DISMISSED") && <button disabled={busy} onClick={() => choose("dismiss")}>Dismiss</button>}
        </div>
      )}
      {open === "confirm" && (
        <div style={{ marginTop: 8 }}>
          <label>
            Owner:{" "}
            <select value={owner} onChange={(e) => setOwner(e.target.value)}>
              {owners.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </label>{" "}
          <label>
            Due date: <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>{" "}
          <button disabled={busy || !due}
                  onClick={() => act("POST", "/confirm", { owner_user_id: owner, due_date: due }, "Finding confirmed.")}>
            Confirm finding
          </button>
        </div>
      )}
      {(open === "return" || open === "dismiss") && (
        <div style={{ marginTop: 8 }}>
          <label>
            {open === "return" ? "Note for the author (required):" : "Reason for dismissing (required):"}
            <br />
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} cols={60} />
          </label>
          <br />
          <button
            disabled={busy || !text.trim()}
            onClick={() =>
              open === "return"
                ? act("POST", "/return", { note: text }, "Returned to the author.")
                : act("POST", "/dismiss", { reason: text }, "Finding dismissed.")
            }
          >
            {open === "return" ? "Return" : "Dismiss finding"}
          </button>
        </div>
      )}
    </div>
  );
}
