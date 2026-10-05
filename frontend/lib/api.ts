// DEVELOPMENT ONLY identity: matches the backend's temporary header login.
// Replace with the platform's real JWT login when it exists.
export const DEV_TENANT_ID = "22222222-2222-2222-2222-222222222222";
const DEV_USER_ID = "11111111-1111-1111-1111-111111111111";
export const DEV_ROLES = ["AUD", "AM", "CO", "OWN", "MGT", "ADM"];

export async function apiGet<T>(path: string, role: string): Promise<{ status: number; data: T | null }> {
  const res = await fetch(`/api/v1${path}`, {
    headers: { "X-User-Id": DEV_USER_ID, "X-Tenant-Id": DEV_TENANT_ID, "X-Roles": role },
    cache: "no-store",
  });
  return { status: res.status, data: res.ok ? ((await res.json()) as T) : null };
}
