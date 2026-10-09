import type { Note } from "@/lib/useStep";

/** The green/red message after a step (see lib/useStep). */
export function StepNote({ note }: { note: Note }) {
  if (!note) return null;
  return <p role="status" style={{ color: note.kind === "ok" ? "#2e7d32" : "#c62828" }}>{note.text}</p>;
}
