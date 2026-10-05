"use client";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { useDevRole } from "@/components/DevRole";

type Me = { roles: string[]; permissions: string[] };

export default function AuditOverview() {
  const { role } = useDevRole();
  const [health, setHealth] = useState("Checking...");
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    apiGet<{ status: string }>("/health", role)
      .then((r) => setHealth(r.data?.status === "ok" ? "API online" : "API not reachable"))
      .catch(() => setHealth("API not reachable"));
    apiGet<Me>("/audit/me", role)
      .then((r) => setMe(r.data))
      .catch(() => setMe(null));
  }, [role]);

  return (
    <div>
      <h1>Audit overview</h1>
      <p>Status: {health}</p>
      <h3>Signed in (development) as: {me?.roles.join(", ") ?? "-"}</h3>
      <p>Permissions ({me?.permissions.length ?? 0}):</p>
      <ul style={{ columns: 2 }}>
        {me?.permissions.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </div>
  );
}
