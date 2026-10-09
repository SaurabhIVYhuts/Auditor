"use client";
// The findings of one case, and "New finding" (opens the new finding's page).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { actionProblem } from "@/lib/apiErrors";
import { type Finding } from "@/lib/findings";
import { useDevRole } from "@/components/DevRole";
import { FindingStatusBadge } from "@/components/RuleBadges";

const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;

export function CaseFindings({ caseId }: { caseId: string }) {
  const { role } = useDevRole();
  const router = useRouter();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Finding[]>(`/audit/findings?case_id=${caseId}`, role)
      .then((r) => {
        setFindings(r.data);
        setLoadProblem(r.status === 200 ? null
          : r.status === 403 ? "Your role cannot view findings." : `Could not load findings (HTTP ${r.status}).`);
      })
      .catch(() => setLoadProblem("API not reachable. Is the backend running?"));
  }, [caseId, role]);

  async function create() {
    setBusy(true);
    setProblem(null);
    try {
      const r = await apiPost<Finding>(`/audit/cases/${caseId}/findings`, role, { title: title.trim() });
      if (r.status === 201 && r.data) router.push(`/audit/findings/${r.data.id}`);
      else setProblem(actionProblem(r.status, r.error, "Case not found or not visible to your role."));
    } catch {
      setProblem("API not reachable. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={box}>
      <h3 style={{ marginTop: 0 }}>Findings</h3>
      {loadProblem && <p>{loadProblem}</p>}
      {findings && findings.length === 0 && <p>No findings yet.</p>}
      {findings && findings.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {findings.map((f) => (
            <li key={f.id} style={{ margin: "4px 0" }}>
              <Link href={`/audit/findings/${f.id}`}>{f.finding_number}</Link> {f.title}{" "}
              <FindingStatusBadge status={f.status} />
            </li>
          ))}
        </ul>
      )}
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title of the new finding"
             aria-label="New finding title" size={50} />{" "}
      <button disabled={busy || title.trim().length < 3} onClick={create}>New finding</button>
      {problem && <p role="status" style={{ color: "#c62828", marginBottom: 0 }}>{problem}</p>}
    </div>
  );
}
