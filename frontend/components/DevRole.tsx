"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import { DEV_ROLES } from "@/lib/api";

const RoleContext = createContext<{ role: string; setRole: (r: string) => void }>({
  role: "AUD",
  setRole: () => {},
});

export function DevRoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState("AUD");
  return <RoleContext.Provider value={{ role, setRole }}>{children}</RoleContext.Provider>;
}

export function useDevRole() {
  return useContext(RoleContext);
}

export function DevRoleSelect() {
  const { role, setRole } = useDevRole();
  return (
    <label style={{ fontSize: 13 }}>
      Dev role:{" "}
      <select value={role} onChange={(e) => setRole(e.target.value)}>
        {DEV_ROLES.map((r) => (
          <option key={r}>{r}</option>
        ))}
      </select>
    </label>
  );
}
