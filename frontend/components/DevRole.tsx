"use client";
// DEVELOPMENT ONLY: pick who you are (user + role) for the backend's temporary header login.
// Replace with the platform's real JWT login when it exists.
import { createContext, useContext, useState, type ReactNode } from "react";
import { DEV_ROLES, DEV_USERS, DEV_USER_ID, setDevUserId } from "@/lib/api";

const RoleContext = createContext<{
  role: string;
  setRole: (r: string) => void;
  userId: string;
  setUserId: (id: string) => void;
}>({ role: "AUD", setRole: () => {}, userId: DEV_USER_ID, setUserId: () => {} });

export function DevRoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState("AUD");
  const [userId, setUser] = useState(DEV_USER_ID);
  function setUserId(id: string) {
    setDevUserId(id);                     // used by every API call (lib/api.ts)
    setUser(id);
  }
  return (
    <RoleContext.Provider value={{ role, setRole, userId, setUserId }}>
      {/* key: switching user reloads the page content as that user */}
      <div key={userId} style={{ display: "contents" }}>{children}</div>
    </RoleContext.Provider>
  );
}

export function useDevRole() {
  return useContext(RoleContext);
}

export function DevRoleSelect() {
  const { role, setRole, userId, setUserId } = useDevRole();
  return (
    <div style={{ fontSize: 13 }}>
      <label>
        Dev user:{" "}
        <select value={userId} onChange={(e) => setUserId(e.target.value)}>
          {DEV_USERS.map((u) => (
            <option key={u.id} value={u.id}>{u.name}</option>
          ))}
        </select>
      </label>
      <br />
      <label>
        Dev role:{" "}
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          {DEV_ROLES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </label>
    </div>
  );
}
