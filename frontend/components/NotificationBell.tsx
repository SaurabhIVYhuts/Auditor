"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";

type Notification = {
  id: string;
  title: string;
  body: string;
  entity_type: string | null;
  entity_id: string | null;
  created_at: string;
};

const REFRESH_MS = 30_000;

export function NotificationBell() {
  const { role } = useDevRole();
  const router = useRouter();
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(
    () =>
      apiGet<Notification[]>("/notifications?unread_only=true", role)
        .then((r) => setItems(r.status === 200 ? r.data ?? [] : []))
        .catch(() => setItems([])),
    [role],
  );

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  function toggle() {
    setOpen((o) => !o);
    refresh();
  }

  async function select(n: Notification) {
    await apiPost(`/notifications/${n.id}/read`, role).catch(() => null);
    setOpen(false);
    await refresh();
    if (n.entity_type === "audit_case" && n.entity_id) router.push(`/audit/cases/${n.entity_id}`);
  }

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button onClick={toggle} aria-label={`Notifications (${items.length} unread)`} aria-expanded={open}>
        🔔{" "}
        {items.length > 0 && (
          <span style={{ background: "#c62828", color: "#fff", borderRadius: 10, padding: "0 6px", fontSize: 12 }}>
            {items.length}
          </span>
        )}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          style={{
            position: "absolute", right: 0, top: "110%", width: 320, background: "#fff", color: "#111",
            border: "1px solid #ccc", borderRadius: 6, boxShadow: "0 4px 12px rgba(0,0,0,0.15)", zIndex: 10,
          }}
        >
          {items.length === 0 ? (
            <p style={{ margin: 12 }}>No new notifications.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {items.map((n) => (
                <li key={n.id} style={{ borderBottom: "1px solid #eee" }}>
                  <button
                    onClick={() => select(n)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: 10, background: "none",
                             border: "none", cursor: "pointer" }}
                  >
                    <strong>{n.title}</strong>
                    <div style={{ fontSize: 13 }}>{n.body}</div>
                    <div style={{ fontSize: 12, opacity: 0.7 }}>{new Date(n.created_at).toLocaleString()}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
