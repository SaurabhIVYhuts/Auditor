"use client";
import { useState, type FormEvent } from "react";
import { apiGet } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";

type Entry = {
  source_record_id: string;
  entity_type: string;
  captured_at: string;
  checksum_ok: boolean;
  snapshot: Record<string, unknown>;
};

const LABELS: Record<string, string> = {
  purchase_order: "Purchase order",
  grn: "Goods receipt (GRN)",
  invoice: "Invoice",
  payment: "Payment",
};

const NUMBER_FIELD: Record<string, string> = {
  purchase_order: "po_number",
  grn: "grn_number",
  invoice: "invoice_number",
  payment: "payment_ref",
};

function documentNumber(e: Entry): string {
  const value = e.snapshot[NUMBER_FIELD[e.entity_type] ?? ""];
  return value ? String(value) : "-";
}

export default function TrailPage() {
  const { role } = useDevRole();
  const [po, setPo] = useState("PO-MOCK-00001");
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [message, setMessage] = useState("");

  async function search(e: FormEvent) {
    e.preventDefault();
    setEntries(null);
    setMessage("Loading...");
    try {
      const r = await apiGet<Entry[]>(`/audit/trail/po/${encodeURIComponent(po)}`, role);
      if (r.status === 403) setMessage("Your role is not allowed to view procurement trails.");
      else if (r.status !== 200) setMessage(`Could not load the trail (HTTP ${r.status}).`);
      else {
        setEntries(r.data ?? []);
        setMessage(r.data && r.data.length > 0 ? "" : "No snapshots found for this PO.");
      }
    } catch {
      setMessage("API not reachable. Is the backend running?");
    }
  }

  return (
    <div>
      <h1>Procurement trail</h1>
      <form onSubmit={search} style={{ marginBottom: 16 }}>
        <input value={po} onChange={(e) => setPo(e.target.value)} placeholder="PO number" />{" "}
        <button type="submit">Show trail</button>
      </form>
      {message && <p>{message}</p>}
      {entries && entries.length > 0 && (
        <table cellPadding={8} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Step</th>
              <th align="left">Document</th>
              <th align="left">Number</th>
              <th align="left">Captured</th>
              <th align="left">Integrity</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr key={e.source_record_id} style={{ borderTop: "1px solid #ccc" }}>
                <td>{i + 1}</td>
                <td>{LABELS[e.entity_type] ?? e.entity_type}</td>
                <td>{documentNumber(e)}</td>
                <td>{new Date(e.captured_at).toLocaleString()}</td>
                <td>{e.checksum_ok ? "✔ Verified" : "⚠ Changed since capture"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
