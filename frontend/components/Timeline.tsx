import { type TimelineEntry, actorLabel, describeEntry } from "@/lib/caseTimeline";

/** The audit-log entries of a case or finding, oldest first, in plain words. */
export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) return <p>Nothing recorded yet.</p>;
  return (
    <ol style={{ paddingLeft: 20 }}>
      {entries.map((t, i) => (
        <li key={i} style={{ marginBottom: 4 }}>
          {describeEntry(t)}{" "}
          <small style={{ opacity: 0.7 }}>— {actorLabel(t.actor_id)}, {new Date(t.created_at).toLocaleString()}</small>
        </li>
      ))}
    </ol>
  );
}
