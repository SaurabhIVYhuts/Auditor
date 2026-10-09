import { DEV_USERS, devUserId } from "@/lib/api";

/** "Me" for the selected dev user, a name for the other dev users, "-" for nobody,
 *  otherwise the first 8 characters of the id. */
export function personLabel(id: string | null | undefined): string {
  if (!id) return "-";
  if (id === devUserId()) return "Me";
  return DEV_USERS.find((u) => u.id === id)?.name ?? shortId(id);
}

/** First 8 characters of an id, for tables (show the full id on hover). */
export function shortId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

/** "IN_INVESTIGATION" -> "In investigation". */
export function label(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " ");
}

/** Today as YYYY-MM-DD in the browser's time zone (due dates are plain dates). */
export function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Past its due date and not in one of the finished statuses. */
export function isPastDue(dueDate: string | null, status: string, finished: ReadonlySet<string>): boolean {
  return !!dueDate && dueDate < today() && !finished.has(status);
}
