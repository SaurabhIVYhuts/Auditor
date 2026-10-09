import { isPastDue } from "@/lib/format";

// Shapes and helpers shared by My Actions, the action page and the finding's actions list.

export type Action = {
  id: string;
  action_number: string;
  finding_id: string;
  finding_number: string;
  case_id: string;
  case_number: string;
  description: string;
  owner_user_id: string;
  due_date: string;                    // YYYY-MM-DD
  status: string;
  submitted_at: string | null;
  verified_by: string | null;
  verified_at: string | null;
  verification_note: string | null;
  return_note: string | null;
  closed_at: string | null;
  allowed_next: string[];
};

const DONE = new Set(["VERIFIED", "CLOSED"]);

/** Past its due date and not yet verified or closed. */
export function isActionOverdue(a: Pick<Action, "due_date" | "status">): boolean {
  return isPastDue(a.due_date, a.status, DONE);
}

// Roles that create, verify and return actions (the server checks again; this only hides buttons).
export const AUDIT_TEAM = new Set(["AUD", "AM"]);
