// DEVELOPMENT ONLY identity: matches the backend's temporary header login.
// Replace with the platform's real JWT login when it exists.
export const DEV_TENANT_ID = "22222222-2222-2222-2222-222222222222";
export const DEV_ROLES = ["AUD", "AM", "CO", "OWN", "MGT", "ADM"];
export const DEV_USERS = [
  { id: "11111111-1111-1111-1111-111111111111", name: "Priya" },
  { id: "44444444-4444-4444-4444-444444444444", name: "Rahul" },
  { id: "55555555-5555-5555-5555-555555555555", name: "Sunita" },
];
export const DEV_USER_ID = DEV_USERS[0].id;          // the default user

// The user picked in the dev switcher (components/DevRole sets it).
let currentUserId = DEV_USER_ID;

export function setDevUserId(id: string): void {
  currentUserId = id;
}

export function devUserId(): string {
  return currentUserId;
}

function devHeaders(role: string): Record<string, string> {
  return { "X-User-Id": currentUserId, "X-Tenant-Id": DEV_TENANT_ID, "X-Roles": role };
}

function send(path: string, role: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...devHeaders(role), ...(init.headers as Record<string, string> | undefined) },
    cache: "no-store",
  });
}

export async function apiGet<T>(path: string, role: string): Promise<{ status: number; data: T | null }> {
  const res = await send(path, role);
  return { status: res.status, data: res.ok ? ((await res.json()) as T) : null };
}

// FastAPI error body, e.g. {"detail": "MAKER_CHECKER"} or {"detail": {"errors": [...]}}.
export type ApiError = { detail?: unknown } | null;
export type ApiResult<T> = { status: number; data: T | null; error: ApiError };

async function result<T>(res: Response): Promise<ApiResult<T>> {
  const parsed = await res.json().catch(() => null);
  return res.ok
    ? { status: res.status, data: parsed as T, error: null }
    : { status: res.status, data: null, error: parsed as ApiError };
}

export async function apiPost<T>(path: string, role: string, body?: unknown): Promise<ApiResult<T>> {
  return result<T>(await send(path, role, {
    method: "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }));
}

/** Multipart upload (files). The browser sets the Content-Type with its boundary. */
export async function apiUpload<T>(path: string, role: string, form: FormData): Promise<ApiResult<T>> {
  return result<T>(await send(path, role, { method: "POST", body: form }));
}

/** GET a download: a file comes back as a Blob, a JSON answer (e.g. a snapshot) as data. */
export async function apiDownload(
  path: string,
  role: string,
): Promise<{ status: number; blob: Blob | null; json: unknown; error: ApiError }> {
  const res = await send(path, role);
  if (!res.ok) return { status: res.status, blob: null, json: null, error: await res.json().catch(() => null) };
  if ((res.headers.get("Content-Type") ?? "").includes("application/json")) {
    return { status: res.status, blob: null, json: await res.json(), error: null };
  }
  return { status: res.status, blob: await res.blob(), json: null, error: null };
}
