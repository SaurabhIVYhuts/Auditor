"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";

type Rule = {
  id: string;
  rule_code: string;
  name: string;
  domain: string;
  severity: string;
  status: string;
  current_version: number;
};

type Load =
  | { state: "loading" }
  | { state: "ready"; rules: Rule[] }
  | { state: "error"; message: string };

const SEVERITY_COLOURS: Record<string, string> = {
  LOW: "#2e7d32",
  MEDIUM: "#b26a00",
  HIGH: "#c62828",
  CRITICAL: "#6a1b9a",
};

const STATUS_COLOURS: Record<string, string> = {
  DRAFT: "#616161",
  ACTIVE: "#1565c0",
  INACTIVE: "#9e9e9e",
};

const FILTERS = ["ALL", "DRAFT", "ACTIVE", "INACTIVE"] as const;
type Filter = (typeof FILTERS)[number];

function Badge({ text, colour }: { text: string; colour: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 12,
        fontWeight: 600,
        color: "#fff",
        background: colour,
      }}
    >
      {text}
    </span>
  );
}

function errorMessage(status: number): string {
  if (status === 401) return "You are not signed in.";
  if (status === 403) return "Your role is not allowed to view rules.";
  return `Could not load rules (HTTP ${status}).`;
}

export default function RulesPage() {
  const { role } = useDevRole();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [filter, setFilter] = useState<Filter>("ALL");

  useEffect(() => {
    apiGet<Rule[]>("/audit/rules", role)
      .then((r) =>
        setLoad(r.status === 200 ? { state: "ready", rules: r.data ?? [] } : { state: "error", message: errorMessage(r.status) }),
      )
      .catch(() => setLoad({ state: "error", message: "API not reachable. Is the backend running?" }));
  }, [role]);

  const rules = load.state === "ready" ? load.rules : [];
  const shown = filter === "ALL" ? rules : rules.filter((r) => r.status === filter);

  return (
    <div>
      <h1>Rules</h1>
      <div style={{ marginBottom: 16 }}>
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{ marginRight: 8, fontWeight: filter === f ? 700 : 400 }}
            aria-pressed={filter === f}
          >
            {f === "ALL" ? "All" : f.charAt(0) + f.slice(1).toLowerCase()}
          </button>
        ))}
      </div>

      {load.state === "loading" && <p>Loading...</p>}
      {load.state === "error" && <p>{load.message}</p>}
      {load.state === "ready" && rules.length === 0 && <p>No rules yet.</p>}
      {load.state === "ready" && rules.length > 0 && shown.length === 0 && <p>No rules with this status.</p>}

      {load.state === "ready" && shown.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Code</th>
              <th align="left">Name</th>
              <th align="left">Domain</th>
              <th align="left">Severity</th>
              <th align="left">Status</th>
              <th align="left">Version</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #ccc" }}>
                <td>
                  <Link href={`/audit/rules/${r.id}`}>{r.rule_code}</Link>
                </td>
                <td>{r.name}</td>
                <td>{r.domain}</td>
                <td>
                  <Badge text={r.severity} colour={SEVERITY_COLOURS[r.severity] ?? "#616161"} />
                </td>
                <td>
                  <Badge text={r.status} colour={STATUS_COLOURS[r.status] ?? "#616161"} />
                </td>
                <td>v{r.current_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
