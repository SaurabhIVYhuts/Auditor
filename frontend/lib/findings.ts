// Shapes and helpers shared by the findings register, the case's findings list and the finding page.

export type Finding = {
  id: string;
  finding_number: string;
  case_id: string;
  title: string;
  condition: string | null;
  criteria: string | null;
  cause: string | null;
  effect: string | null;
  recommendation: string | null;
  financial_impact: string | null;     // a decimal, sent by the API as a string
  risk_level: string | null;
  owner_user_id: string | null;
  due_date: string | null;             // YYYY-MM-DD
  status: string;
  dismiss_reason: string | null;
  created_by: string | null;
  created_at: string;
  submitted_by: string | null;
  submitted_at: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  allowed_next: string[];
};

export const FINDING_STATUSES = [
  "DRAFT", "UNDER_REVIEW", "CONFIRMED", "DISMISSED", "ACTION_ASSIGNED", "RESOLVED", "VERIFIED", "REOPENED", "CLOSED",
];
export const RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const FINISHED = new Set(["CLOSED", "DISMISSED"]);

/** Today as YYYY-MM-DD in the browser's time zone (due dates are plain dates). */
function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Past its due date and not closed or dismissed. */
export function isOverdue(f: Pick<Finding, "due_date" | "status">): boolean {
  return !!f.due_date && f.due_date < today() && !FINISHED.has(f.status);
}
