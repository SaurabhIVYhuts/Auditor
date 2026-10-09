"use client";
// The corrective actions of one finding: list, "Add action", and "Close finding" once all are verified.
import Link from "next/link";
import { useEffect, useState } from "react";
import { DEV_USERS, apiGet, apiPost } from "@/lib/api";
import { AUDIT_TEAM, type Action, isActionOverdue } from "@/lib/actions";
import { UNREACHABLE, actionProblem } from "@/lib/apiErrors";
import { type Finding, TAKES_ACTIONS } from "@/lib/findings";
import { personLabel } from "@/lib/format";
import { useStep } from "@/lib/useStep";
import { useDevRole } from "@/components/DevRole";
import { ActionStatusBadge } from "@/components/RuleBadges";
import { StepNote } from "@/components/StepNote";

const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;
const overdueStyle = { color: "#c62828", fontWeight: 600 } as const;
const NOT_FOUND = "Finding not found or not visible to your role.";

export function ActionsSection({ finding, onChanged }: { finding: Finding; onChanged: () => unknown }) {
  const { role } = useDevRole();
  const [actions, setActions] = useState<Action[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState(finding.owner_user_id ?? DEV_USERS[0].id);
  const [due, setDue] = useState(finding.due_date ?? "");
  const [refresh, setRefresh] = useState(0);
  const { busy, note, run } = useStep((status, error) => actionProblem(status, error, NOT_FOUND), () => {
    setRefresh((n) => n + 1);           // reload the list...
    return onChanged();                 // ...and the finding (its status follows its actions)
  });
  const team = AUDIT_TEAM.has(role);

  useEffect(() => {
    apiGet<Action[]>(`/audit/actions?finding_id=${finding.id}`, role)
      .then((r) => {
        setActions(r.data);
        setLoadProblem(r.status === 200 ? null
          : r.status === 403 ? "Your role cannot view corrective actions." : `Could not load actions (HTTP ${r.status}).`);
      })
      .catch(() => setLoadProblem(UNREACHABLE));
  }, [finding.id, role, refresh]);

  async function add() {
    const ok = await run(() => apiPost(`/audit/findings/${finding.id}/actions`, role,
      { description: description.trim(), owner_user_id: owner, due_date: due || null }), "Action added.");
    if (ok) setDescription("");
  }

  const owners = DEV_USERS.some((u) => u.id === owner) ? DEV_USERS : [...DEV_USERS, { id: owner, name: personLabel(owner) }];

  return (
    <div style={box}>
      <h3 style={{ marginTop: 0 }}>Corrective actions</h3>
      {loadProblem && <p>{loadProblem}</p>}
      {actions && actions.length === 0 && <p>No corrective actions yet.</p>}
      {actions && actions.length > 0 && (
        <table cellPadding={6} style={{ borderCollapse: "collapse", marginBottom: 12 }}>
          <thead>
            <tr>
              <th align="left">Action no.</th><th align="left">Description</th><th align="left">Owner</th>
              <th align="left">Due date</th><th align="left">Status</th>
            </tr>
          </thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a.id} style={{ borderTop: "1px solid #ccc" }}>
                <td><Link href={`/audit/actions/${a.id}`}>{a.action_number}</Link></td>
                <td>{a.description}</td>
                <td title={a.owner_user_id}>{personLabel(a.owner_user_id)}</td>
                <td style={isActionOverdue(a) ? overdueStyle : undefined}>
                  {a.due_date}{isActionOverdue(a) && " (overdue)"}
                </td>
                <td><ActionStatusBadge status={a.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {team && TAKES_ACTIONS.has(finding.status) && (
        <div style={{ borderTop: "1px solid #eee", paddingTop: 8 }}>
          <strong>Add action</strong>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
                    placeholder="What must be done" aria-label="Action description"
                    style={{ display: "block", width: "100%", maxWidth: 700, margin: "6px 0" }} />
          <label>
            Owner:{" "}
            <select value={owner} onChange={(e) => setOwner(e.target.value)}>
              {owners.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </label>{" "}
          <label>
            Due date: <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>{" "}
          <button disabled={busy || !description.trim() || !due} onClick={add}>Add action</button>
        </div>
      )}

      {team && finding.status === "VERIFIED" && (
        <button disabled={busy}
                onClick={() => run(() => apiPost(`/audit/findings/${finding.id}/close`, role), "Finding closed.")}>
          Close finding
        </button>
      )}
      <StepNote note={note} />
    </div>
  );
}
