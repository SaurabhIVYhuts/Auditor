"use client";
// Evidence of one case: list, download, verify the fingerprint, upload, supersede.
// The server decides what each role may do; this page only shows its answers.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiDownload, apiGet, apiPost, apiUpload } from "@/lib/api";
import { actionProblem, errorInfo } from "@/lib/apiErrors";
import { label, personLabel } from "@/lib/format";
import { useDevRole } from "@/components/DevRole";
import { EvidenceStatusBadge } from "@/components/RuleBadges";

type Evidence = {
  id: string;
  title: string;
  evidence_type: string;
  source_system: string;
  sha256: string;
  status: string;
  superseded_reason: string | null;
  contains_phi: boolean;
  captured_by: string | null;
  captured_at: string;
  filename: string | null;
  is_snapshot: boolean;
};

type RowNote = { kind: "ok" | "problem"; text: string };

const EVIDENCE_TYPES = ["DOCUMENT", "EMAIL", "APPROVAL", "LOG", "ATTACHMENT", "CHECKLIST", "TRANSACTION"];
const NOT_FOUND = "Evidence not found or not visible to your role.";
const MISMATCH = "Fingerprint mismatch - Audit Managers alerted";
const UNREACHABLE = "API not reachable. Is the backend running?";

const box = { border: "1px solid #ddd", borderRadius: 6, padding: 12, marginBottom: 16 } as const;
const problemColour = "#c62828";

function problem(status: number, error: Parameters<typeof actionProblem>[1]): string {
  return status === 409 && errorInfo(error).code === "INTEGRITY_FAILED" ? MISMATCH : actionProblem(status, error, NOT_FOUND);
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function EvidenceSection({ caseId }: { caseId: string }) {
  const { role } = useDevRole();
  const [items, setItems] = useState<Evidence[] | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, RowNote>>({});
  const [snapshots, setSnapshots] = useState<Record<string, unknown>>({});   // opened snapshot rows
  const [supersedeId, setSupersedeId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  // upload form
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [evidenceType, setEvidenceType] = useState("DOCUMENT");
  const [containsPhi, setContainsPhi] = useState(false);
  const [uploadNote, setUploadNote] = useState<RowNote | null>(null);
  const [formKey, setFormKey] = useState(0);          // bump to clear the file input

  const reload = useCallback(
    () =>
      apiGet<Evidence[]>(`/audit/cases/${caseId}/evidence`, role)
        .then((r) => {
          setItems(r.data);
          setLoadProblem(r.status === 200 ? null
            : r.status === 403 ? "Your role cannot view evidence." : `Could not load evidence (HTTP ${r.status}).`);
        })
        .catch(() => setLoadProblem(UNREACHABLE)),
    [caseId, role],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  function note(id: string, value: RowNote) {
    setNotes((n) => ({ ...n, [id]: value }));
  }

  async function run(id: string, work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
    } catch {
      note(id, { kind: "problem", text: UNREACHABLE });
    } finally {
      setBusy(false);
    }
  }

  function download(e: Evidence) {
    if (snapshots[e.id] !== undefined) {                       // second click closes the snapshot
      setSnapshots((s) => {
        const rest = { ...s };
        delete rest[e.id];
        return rest;
      });
      return;
    }
    run(e.id, async () => {
      const r = await apiDownload(`/audit/evidence/${e.id}/download`, role);
      if (r.status !== 200) return note(e.id, { kind: "problem", text: problem(r.status, r.error) });
      if (r.blob) saveBlob(r.blob, e.filename ?? "evidence");
      else setSnapshots((s) => ({ ...s, [e.id]: r.json }));
    });
  }

  function verify(e: Evidence) {
    run(e.id, async () => {
      const r = await apiPost<{ ok: boolean }>(`/audit/evidence/${e.id}/verify`, role);
      if (r.status !== 200) return note(e.id, { kind: "problem", text: problem(r.status, r.error) });
      note(e.id, r.data?.ok ? { kind: "ok", text: "Fingerprint OK" } : { kind: "problem", text: MISMATCH });
    });
  }

  function supersede(e: Evidence) {
    run(e.id, async () => {
      const r = await apiPost(`/audit/evidence/${e.id}/supersede`, role, { reason });
      if (r.status !== 200) return note(e.id, { kind: "problem", text: problem(r.status, r.error) });
      note(e.id, { kind: "ok", text: "Marked as superseded." });
      setSupersedeId(null);
      setReason("");
      await reload();
    });
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
    form.append("evidence_type", evidenceType);
    form.append("contains_phi", String(containsPhi));
    setBusy(true);
    try {
      const r = await apiUpload<Evidence>(`/audit/cases/${caseId}/evidence`, role, form);
      if (r.status !== 201) {
        setUploadNote({ kind: "problem", text: actionProblem(r.status, r.error, NOT_FOUND) });
        return;
      }
      setUploadNote({ kind: "ok", text: `Uploaded "${r.data?.title}".` });
      setTitle("");
      setFile(null);
      setContainsPhi(false);
      setFormKey((k) => k + 1);
      await reload();
    } catch {
      setUploadNote({ kind: "problem", text: UNREACHABLE });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={box}>
      <h3 style={{ marginTop: 0 }}>Evidence</h3>
      {loadProblem && <p>{loadProblem}</p>}
      {items && items.length === 0 && <p>No evidence yet.</p>}
      {items && items.length > 0 && (
        <table cellPadding={6} style={{ borderCollapse: "collapse", marginBottom: 12, width: "100%" }}>
          <thead>
            <tr>
              <th align="left">Title</th><th align="left">Type</th><th align="left">Source</th>
              <th align="left">Fingerprint</th><th align="left">Status</th><th align="left">Captured</th><th />
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <EvidenceRow key={e.id} e={e} busy={busy} note={notes[e.id]} snapshot={snapshots[e.id]}
                           supersedeOpen={supersedeId === e.id} reason={reason} setReason={setReason}
                           onDownload={() => download(e)} onVerify={() => verify(e)}
                           onSupersedeOpen={() => { setSupersedeId(e.id); setReason(""); }}
                           onSupersedeCancel={() => setSupersedeId(null)} onSupersede={() => supersede(e)} />
            ))}
          </tbody>
        </table>
      )}

      <form key={formKey} onSubmit={upload} style={{ borderTop: "1px solid #eee", paddingTop: 8 }}>
        <strong>Upload evidence</strong>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
          <input value={title} onChange={(ev) => setTitle(ev.target.value)} placeholder="Title" aria-label="Title" size={30} />
          <input type="file" aria-label="File" onChange={(ev) => setFile(ev.target.files?.[0] ?? null)} />
          <select value={evidenceType} onChange={(ev) => setEvidenceType(ev.target.value)} aria-label="Type">
            {EVIDENCE_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
          <label>
            <input type="checkbox" checked={containsPhi} onChange={(ev) => setContainsPhi(ev.target.checked)} />{" "}
            Contains patient data
          </label>
          <button type="submit" disabled={busy || !title.trim() || !file}>Upload</button>
        </div>
        {uploadNote && (
          <p role="status" style={{ color: uploadNote.kind === "ok" ? "#2e7d32" : problemColour, marginBottom: 0 }}>
            {uploadNote.text}
          </p>
        )}
      </form>
    </div>
  );
}

type RowProps = {
  e: Evidence;
  busy: boolean;
  note?: RowNote;
  snapshot: unknown;
  supersedeOpen: boolean;
  reason: string;
  setReason: (r: string) => void;
  onDownload: () => void;
  onVerify: () => void;
  onSupersedeOpen: () => void;
  onSupersedeCancel: () => void;
  onSupersede: () => void;
};

function EvidenceRow(p: RowProps) {
  const { e } = p;
  const active = e.status === "ACTIVE";
  return (
    <>
      <tr style={{ borderTop: "1px solid #ccc", opacity: active ? 1 : 0.7 }}>
        <td>{e.title}{e.contains_phi && <small style={{ color: problemColour }}> (patient data)</small>}</td>
        <td>{label(e.evidence_type)}</td>
        <td>{e.is_snapshot ? `System snapshot (${e.source_system})` : (e.filename ?? "-")}</td>
        <td title={e.sha256}><code>{e.sha256.slice(0, 12)}…</code></td>
        <td>
          <EvidenceStatusBadge status={e.status} />
          {e.superseded_reason && <div><small>{e.superseded_reason}</small></div>}
        </td>
        <td>
          <span title={e.captured_by ?? undefined}>{e.captured_by ? personLabel(e.captured_by) : "System"}</span>
          <div><small>{new Date(e.captured_at).toLocaleString()}</small></div>
        </td>
        <td style={{ whiteSpace: "nowrap" }}>
          <button disabled={p.busy} onClick={p.onDownload}>
            {e.is_snapshot ? (p.snapshot !== undefined ? "Hide" : "View") : "Download"}
          </button>{" "}
          <button disabled={p.busy} onClick={p.onVerify}>Verify</button>{" "}
          {active && <button disabled={p.busy} onClick={p.onSupersedeOpen}>Supersede</button>}
        </td>
      </tr>
      {p.note && (
        <tr>
          <td colSpan={7} role="status" style={{ color: p.note.kind === "ok" ? "#2e7d32" : problemColour, paddingTop: 0 }}>
            {p.note.text}
          </td>
        </tr>
      )}
      {p.supersedeOpen && (
        <tr>
          <td colSpan={7}>
            <label>
              Reason for superseding (required):
              <br />
              <textarea value={p.reason} onChange={(ev) => p.setReason(ev.target.value)} rows={2} cols={60} />
            </label>
            <br />
            <button disabled={p.busy || !p.reason.trim()} onClick={p.onSupersede}>Confirm</button>{" "}
            <button disabled={p.busy} onClick={p.onSupersedeCancel}>Cancel</button>
          </td>
        </tr>
      )}
      {p.snapshot !== undefined && (
        <tr>
          <td colSpan={7}>
            <pre style={{ background: "#f6f6f6", padding: 8, maxHeight: 300, overflow: "auto", margin: 0 }}>
              {JSON.stringify(p.snapshot, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}
