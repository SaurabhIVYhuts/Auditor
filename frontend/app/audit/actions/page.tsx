"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { type Action, isActionOverdue } from "@/lib/actions";
import { UNREACHABLE } from "@/lib/apiErrors";
import { useDevRole } from "@/components/DevRole";
import { ActionStatusBadge } from "@/components/RuleBadges";
import styles from "./actions.module.css";

type Load =
  | { state: "loading" }
  | { state: "ready"; actions: Action[] }
  | { state: "error"; message: string };

const overdueStyle = { color: "#c62828", fontWeight: 600 } as const;

function errorMessage(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view corrective actions.";
  return `Could not load actions (HTTP ${status}).`;
}

function Due({ a }: { a: Action }) {
  const overdue = isActionOverdue(a);
  return <span style={overdue ? overdueStyle : undefined}>{a.due_date}{overdue && " · OVERDUE"}</span>;
}

export default function MyActionsPage() {
  const { role } = useDevRole();
  const [all, setAll] = useState(false);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const params = new URLSearchParams();
    if (!all) params.set("mine", "true");
    if (overdueOnly) params.set("overdue_only", "true");
    apiGet<Action[]>(`/audit/actions?${params}`, role)
      .then((r) =>
        setLoad(r.status === 200 ? { state: "ready", actions: r.data ?? [] } : { state: "error", message: errorMessage(r.status) }),
      )
      .catch(() => setLoad({ state: "error", message: UNREACHABLE }));
  }, [role, all, overdueOnly]);

  return (
    <div>
      <h1>{all ? "Corrective actions" : "My actions"}</h1>
      <div style={{ marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 12 }}>
        <label>
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> All I can see
        </label>
        <label>
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} /> Overdue only
        </label>
      </div>

      {load.state === "loading" && <p>Loading...</p>}
      {load.state === "error" && <p>{load.message}</p>}
      {load.state === "ready" && load.actions.length === 0 && (
        <p>{all ? "No actions match these filters." : "No actions are assigned to you."}</p>
      )}

      {load.state === "ready" && load.actions.length > 0 && (
        <>
          <table cellPadding={8} className={styles.table} style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th align="left">Action no.</th>
                <th align="left">Description</th>
                <th align="left">Finding no.</th>
                <th align="left">Case no.</th>
                <th align="left">Due date</th>
                <th align="left">Status</th>
              </tr>
            </thead>
            <tbody>
              {load.actions.map((a) => (
                <tr key={a.id} style={{ borderTop: "1px solid #ccc" }}>
                  <td><Link href={`/audit/actions/${a.id}`}>{a.action_number}</Link></td>
                  <td>{a.description}</td>
                  <td><Link href={`/audit/findings/${a.finding_id}`}>{a.finding_number}</Link></td>
                  <td><Link href={`/audit/cases/${a.case_id}`}>{a.case_number}</Link></td>
                  <td><Due a={a} /></td>
                  <td><ActionStatusBadge status={a.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className={styles.cards}>
            {load.actions.map((a) => (
              <div key={a.id} className={styles.card}>
                <p>
                  <Link href={`/audit/actions/${a.id}`}><strong>{a.action_number}</strong></Link>{" "}
                  <ActionStatusBadge status={a.status} />
                </p>
                <p>{a.description}</p>
                <p><small>Due:</small> <Due a={a} /></p>
                <p>
                  <small>
                    <Link href={`/audit/findings/${a.finding_id}`}>{a.finding_number}</Link>
                    {" · "}
                    <Link href={`/audit/cases/${a.case_id}`}>{a.case_number}</Link>
                  </small>
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
