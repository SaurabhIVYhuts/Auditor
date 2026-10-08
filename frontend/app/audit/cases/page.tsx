"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { DEV_USER_ID, apiGet } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";
import { CaseStatusBadge, SeverityBadge } from "@/components/RuleBadges";

type Case = {
  id: string;
  case_number: string;
  title: string;
  domain: string;
  priority: string;
  status: string;
  assigned_to: string | null;
  opened_at: string;
};

type Load =
  | { state: "loading" }
  | { state: "ready"; cases: Case[]; loadedAt: number }
  | { state: "error"; message: string };

const STATUSES = [
  "OPEN", "ASSIGNED", "IN_INVESTIGATION", "ON_HOLD", "PENDING_REVIEW",
  "FINDING_CONFIRMED", "NO_ISSUE", "ACTION_IN_PROGRESS", "CLOSED", "REOPENED",
];
const PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const DOMAINS = ["PROCUREMENT", "INSURANCE", "BILLING", "FINANCIAL", "COMPLIANCE", "OTHER"];
const DAY_MS = 24 * 60 * 60 * 1000;

function errorMessage(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view cases.";
  return `Could not load cases (HTTP ${status}).`;
}

function label(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " ");
}

function Select({ name, value, options, onChange }: {
  name: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <label style={{ marginRight: 12 }}>
      {name}:{" "}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>{label(o)}</option>
        ))}
      </select>
    </label>
  );
}

export default function CasesPage() {
  const { role } = useDevRole();
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [domain, setDomain] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [mine, setMine] = useState(false);
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (priority) params.set("priority", priority);
    if (domain) params.set("domain", domain);
    if (openOnly) params.set("open_only", "true");
    if (mine) params.set("assigned_to", DEV_USER_ID);
    apiGet<Case[]>(`/audit/cases?${params}`, role)
      .then((r) =>
        setLoad(
          r.status === 200
            ? { state: "ready", cases: r.data ?? [], loadedAt: Date.now() }
            : { state: "error", message: errorMessage(r.status) },
        ),
      )
      .catch(() => setLoad({ state: "error", message: "API not reachable. Is the backend running?" }));
  }, [role, status, priority, domain, openOnly, mine]);

  return (
    <div>
      <h1>Cases</h1>
      <div style={{ marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
        <Select name="Status" value={status} options={STATUSES} onChange={setStatus} />
        <Select name="Priority" value={priority} options={PRIORITIES} onChange={setPriority} />
        <Select name="Domain" value={domain} options={DOMAINS} onChange={setDomain} />
        <label style={{ marginRight: 12 }}>
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> Open only
        </label>
        <label>
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me
        </label>
      </div>

      {load.state === "loading" && <p>Loading...</p>}
      {load.state === "error" && <p>{load.message}</p>}
      {load.state === "ready" && load.cases.length === 0 && <p>No cases match these filters.</p>}

      {load.state === "ready" && load.cases.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Case no.</th>
              <th align="left">Title</th>
              <th align="left">Domain</th>
              <th align="left">Priority</th>
              <th align="left">Status</th>
              <th align="left">Assigned</th>
              <th align="left">Opened</th>
            </tr>
          </thead>
          <tbody>
            {load.cases.map((c) => {
              const opened = new Date(c.opened_at);
              const age = Math.max(0, Math.floor((load.loadedAt - opened.getTime()) / DAY_MS));
              return (
                <tr key={c.id} style={{ borderTop: "1px solid #ccc" }}>
                  <td><Link href={`/audit/cases/${c.id}`}>{c.case_number}</Link></td>
                  <td>{c.title}</td>
                  <td>{label(c.domain)}</td>
                  <td><SeverityBadge severity={c.priority} /></td>
                  <td><CaseStatusBadge status={c.status} /></td>
                  <td title={c.assigned_to ?? undefined}>
                    {c.assigned_to === null ? "-" : c.assigned_to === DEV_USER_ID ? "Me" : `${c.assigned_to.slice(0, 8)}…`}
                  </td>
                  <td>
                    {opened.toLocaleDateString()} ({age} {age === 1 ? "day" : "days"})
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
