import { label, personLabel } from "@/lib/format";

export type TimelineEntry = {
  action: string;
  actor_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

type Change = { from: unknown; to: unknown };

const LONG = 60;          // longer values (e.g. a finding's condition text) are cut in the timeline

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return "none";
  const s = String(value);
  return s.length > LONG ? `${s.slice(0, LONG)}…` : s;
}

function changes(d: Record<string, unknown>): string {
  return Object.entries(d as Record<string, Change>)
    .map(([field, c]) => `${field.replaceAll("_", " ")} ${text(c?.from)} → ${text(c?.to)}`)
    .join("; ");
}

function statusChange(d: Record<string, unknown>): string {
  return `Status ${label(text(d.from))} → ${label(text(d.to))}` + (d.reason ? `: ${d.reason}` : "");
}

/** One plain-language line for a case or finding audit-log entry. Unknown actions fall back to their code. */
export function describeEntry(entry: TimelineEntry): string {
  const d = entry.details ?? {};
  switch (entry.action) {
    case "case.opened":
      return "Case opened";
    case "case.assigned":
      return `Assigned to ${personLabel(d.to as string | null)}` +
        (d.from ? ` (was ${personLabel(d.from as string)})` : "");
    case "case.status_changed":
    case "finding.status_changed":
      return statusChange(d);
    case "case.commented":
      return "Comment added";
    case "case.exception_added":
      return "Exception added";
    case "case.updated":
      return "Case updated: " + changes(d);
    case "finding.created":
      return "Finding created";
    case "finding.updated":
      return "Finding updated: " + changes(d);
    case "finding.submitted":
      return "Submitted for review";
    case "finding.confirmed":
      return `Confirmed; owner ${personLabel(d.owner_user_id as string | null)}, due ${text(d.due_date)}`;
    case "finding.returned":
      return `Returned for changes: ${String(d.note ?? "")}`;      // full note
    case "finding.dismissed":
      return `Dismissed: ${String(d.reason ?? "")}`;
    case "finding.closed":
      return "Finding closed";
    default:
      return entry.action;
  }
}

/** Who did it: "Me", a name, a short id, or "System" for automatic actions. */
export function actorLabel(actorId: string | null): string {
  return actorId ? personLabel(actorId) : "System";
}
