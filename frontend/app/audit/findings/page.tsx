"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, devUserId } from "@/lib/api";
import { personLabel } from "@/lib/format";
import { FINDING_STATUSES, type Finding, RISK_LEVELS, isOverdue } from "@/lib/findings";
import { useDevRole } from "@/components/DevRole";
import { FilterSelect } from "@/components/FilterSelect";
import { FindingStatusBadge, SeverityBadge } from "@/components/RuleBadges";

type Load =
  | { state: "loading" }
  | { state: "ready"; findings: Finding[] }
  | { state: "error"; message: string };

function errorMessage(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view findings.";
  return `Could not load findings (HTTP ${status}).`;
}

export default function FindingsPage() {
  const { role } = useDevRole();
  const [status, setStatus] = useState("");
  const [risk, setRisk] = useState("");
  const [mine, setMine] = useState(false);
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (risk) params.set("risk_level", risk);
    if (mine) params.set("owner_user_id", devUserId());
    apiGet<Finding[]>(`/audit/findings?${params}`, role)
      .then((r) =>
        setLoad(
          r.status === 200
            ? { state: "ready", findings: r.data ?? [] }
            : { state: "error", message: errorMessage(r.status) },
        ),
      )
      .catch(() => setLoad({ state: "error", message: "API not reachable. Is the backend running?" }));
  }, [role, status, risk, mine]);

  return (
    <div>
      <h1>Findings</h1>
      <div style={{ marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
        <FilterSelect name="Status" value={status} options={FINDING_STATUSES} onChange={setStatus} />
        <FilterSelect name="Risk" value={risk} options={RISK_LEVELS} onChange={setRisk} />
        <label>
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Owned by me
        </label>
      </div>

      {load.state === "loading" && <p>Loading...</p>}
      {load.state === "error" && <p>{load.message}</p>}
      {load.state === "ready" && load.findings.length === 0 && <p>No findings match these filters.</p>}

      {load.state === "ready" && load.findings.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Finding no.</th>
              <th align="left">Title</th>
              <th align="left">Case no.</th>
              <th align="left">Risk</th>
              <th align="left">Status</th>
              <th align="left">Owner</th>
              <th align="left">Due date</th>
            </tr>
          </thead>
          <tbody>
            {load.findings.map((f) => {
              const overdue = isOverdue(f);
              return (
                <tr key={f.id} style={{ borderTop: "1px solid #ccc" }}>
                  <td><Link href={`/audit/findings/${f.id}`}>{f.finding_number}</Link></td>
                  <td>{f.title}</td>
                  <td><Link href={`/audit/cases/${f.case_id}`}>{f.case_number}</Link></td>
                  <td>{f.risk_level ? <SeverityBadge severity={f.risk_level} /> : "-"}</td>
                  <td><FindingStatusBadge status={f.status} /></td>
                  <td title={f.owner_user_id ?? undefined}>{personLabel(f.owner_user_id)}</td>
                  <td style={overdue ? { color: "#c62828", fontWeight: 600 } : undefined}
                      title={overdue ? "Past due" : undefined}>
                    {f.due_date ?? "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
