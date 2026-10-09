import type { ApiError } from "@/lib/api";
import { label } from "@/lib/format";

export const UNREACHABLE = "API not reachable. Is the backend running?";

type Info = { code?: string; message?: string; allowed_next?: string[]; missing?: string[] };

/** The structured part of an error body ({code, message, allowed_next}), or {} if there is none. */
export function errorInfo(error: ApiError): Info {
  const detail = error?.detail;
  return detail && typeof detail === "object" && !Array.isArray(detail) ? (detail as Info) : {};
}

/** A plain sentence for a refused action (see backend api/errors.py for the codes). */
export function actionProblem(status: number, error: ApiError, notFound = "Not found or not visible to your role."): string {
  const detail = error?.detail;
  const info = errorInfo(error);
  if (status === 403 && info.code === "MANAGER_APPROVAL") return info.message ?? "Only an Audit Manager can do this.";
  if (status === 403 && info.message) return info.message;           // MAKER_CHECKER, NOT_ALLOWED
  if (status === 403) return "Your role cannot do this.";
  if (status === 404) return notFound;
  if (status === 409 || status === 422) {
    if (Array.isArray(detail)) return "Please check what you entered.";   // request validation errors
    const allowed = info.allowed_next?.length ? ` Allowed next: ${info.allowed_next.map(label).join(", ")}.` : "";
    return `${info.message ?? (typeof detail === "string" ? detail : "The action was refused.")}${allowed}`;
  }
  return `The action did not complete (HTTP ${status}).`;
}
