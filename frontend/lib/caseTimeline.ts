import { label, personLabel } from "@/lib/format";

export type TimelineEntry = {
  action: string;
  actor_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

type Change = { from: unknown; to: unknown };

function text(value: unknown): string {
  return value === null || value === undefined || value === "" ? "none" : String(value);
}

/** One plain-language line for a case audit-log entry. Unknown actions fall back to their code. */
export function describeEntry(entry: TimelineEntry): string {
  const d = entry.details ?? {};
  switch (entry.action) {
    case "case.opened":
      return "Case opened";
    case "case.assigned":
      return `Assigned to ${personLabel(d.to as string | null)}` +
        (d.from ? ` (was ${personLabel(d.from as string)})` : "");
    case "case.status_changed":
      return `Status ${label(text(d.from))} → ${label(text(d.to))}` + (d.reason ? `: ${d.reason}` : "");
    case "case.commented":
      return "Comment added";
    case "case.exception_added":
      return "Exception added";
    case "case.updated":
      return "Case updated: " + Object.entries(d as Record<string, Change>)
        .map(([field, c]) => `${field.replaceAll("_", " ")} ${text(c?.from)} → ${text(c?.to)}`)
        .join("; ");
    default:
      return entry.action;
  }
}

/** Who did it: "Me", a short id, or "System" for automatic actions. */
export function actorLabel(actorId: string | null): string {
  return actorId ? personLabel(actorId) : "System";
}
