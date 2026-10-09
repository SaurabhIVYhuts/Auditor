import Link from "next/link";
import type { ReactNode } from "react";
import { DevRoleProvider, DevRoleSelect } from "@/components/DevRole";
import { NotificationBell } from "@/components/NotificationBell";
import styles from "./layout.module.css";

const NAV: { label: string; href?: string }[] = [
  { label: "Overview", href: "/audit" },
  { label: "Procurement trail", href: "/audit/trail" },
  { label: "Cases", href: "/audit/cases" },
  { label: "Rules", href: "/audit/rules" },
  { label: "Findings", href: "/audit/findings" },
  { label: "My Actions", href: "/audit/actions" },
  { label: "Reports" },
];

export default function AuditLayout({ children }: { children: ReactNode }) {
  return (
    <DevRoleProvider>
      <div className={styles.shell}>
        <nav className={styles.nav}>
          <h2 style={{ fontSize: 18, marginTop: 0 }}>Auditor</h2>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {NAV.map((item) => (
              <li key={item.label} style={{ margin: "10px 0" }}>
                {item.href ? (
                  <Link href={item.href}>{item.label}</Link>
                ) : (
                  <span style={{ opacity: 0.5 }}>{item.label} (coming soon)</span>
                )}
              </li>
            ))}
          </ul>
          <DevRoleSelect />
        </nav>
        <main className={styles.main}>
          <header style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
            <NotificationBell />
          </header>
          {children}
        </main>
      </div>
    </DevRoleProvider>
  );
}
