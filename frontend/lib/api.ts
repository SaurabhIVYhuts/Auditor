// DEVELOPMENT ONLY identity: matches the backend's temporary header login.
// Replace with the platform's real JWT login when it exists.
export const DEV_TENANT_ID = "22222222-2222-2222-2222-222222222222";
const DEV_USER_ID = "11111111-1111-1111-1111-111111111111";
export const DEV_ROLES = ["AUD", "AM", "CO", "OWN", "MGT", "ADM"];

function devHeaders(role: string): Record<string, string> {
  return { "X-User-Id": DEV_USER_ID, "X-Tenant-Id": DEV_TENANT_ID, "X-Roles": role };
}

export async function apiGet<T>(path: string, role: string): Promise<{ status: number; data: T | null }> {
  const res = await fetch(`/api/v1${path}`, {
    headers: devHeaders(role),
    cache: "no-store",
  });
  return { status: res.status, data: res.ok ? ((await res.json()) as T) : null };
}

// FastAPI error body, e.g. {"detail": "MAKER_CHECKER"} or {"detail": {"errors": [...]}}.
export type ApiError = { detail?: unknown } | null;

export async function apiPost<T>(
  path: string,
  role: string,
  body?: unknown,
): Promise<{ status: number; data: T | null; error: ApiError }> {
  const res = await fetch(`/api/v1${path}`, {
    method: "POST",
    headers: { ...devHeaders(role), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const parsed = await res.json().catch(() => null);
  return res.ok
    ? { status: res.status, data: parsed as T, error: null }
    : { status: res.status, data: null, error: parsed as ApiError };
}
