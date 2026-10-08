import { DEV_USER_ID } from "@/lib/api";

/** "Me" for the signed-in dev user, "-" for nobody, otherwise the first 8 characters of the id. */
export function personLabel(id: string | null | undefined): string {
  if (!id) return "-";
  return id === DEV_USER_ID ? "Me" : shortId(id);
}

/** First 8 characters of an id, for tables (show the full id on hover). */
export function shortId(id: string): string {
  return `${id.slice(0, 8)}…`;
}

/** "IN_INVESTIGATION" -> "In investigation". */
export function label(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase().replaceAll("_", " ");
}
