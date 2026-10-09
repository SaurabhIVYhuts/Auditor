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
