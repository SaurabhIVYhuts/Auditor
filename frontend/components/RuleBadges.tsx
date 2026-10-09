const SEVERITY_COLOURS: Record<string, string> = {
  LOW: "#2e7d32",
  MEDIUM: "#b26a00",
  HIGH: "#c62828",
  CRITICAL: "#6a1b9a",
};

const STATUS_COLOURS: Record<string, string> = {
  DRAFT: "#616161",
  ACTIVE: "#1565c0",
  INACTIVE: "#9e9e9e",
};

const CASE_STATUS_COLOURS: Record<string, string> = {
  OPEN: "#455a64",
  ASSIGNED: "#1565c0",
  IN_INVESTIGATION: "#283593",
  ON_HOLD: "#b26a00",
  PENDING_REVIEW: "#6a1b9a",
  FINDING_CONFIRMED: "#c62828",
  NO_ISSUE: "#2e7d32",
  ACTION_IN_PROGRESS: "#00695c",
  CLOSED: "#9e9e9e",
  REOPENED: "#e65100",
};

const FINDING_STATUS_COLOURS: Record<string, string> = {
  DRAFT: "#616161",
  UNDER_REVIEW: "#6a1b9a",
  CONFIRMED: "#c62828",
  DISMISSED: "#9e9e9e",
  ACTION_ASSIGNED: "#00695c",
  RESOLVED: "#1565c0",
  VERIFIED: "#2e7d32",
  REOPENED: "#e65100",
  CLOSED: "#9e9e9e",
};

const EVIDENCE_STATUS_COLOURS: Record<string, string> = {
  ACTIVE: "#2e7d32",
  SUPERSEDED: "#9e9e9e",
};

const FALLBACK_COLOUR = "#616161";

function Badge({ text, colour }: { text: string; colour: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 12,
        fontWeight: 600,
        color: "#fff",
        background: colour,
      }}
    >
      {text}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge text={severity} colour={SEVERITY_COLOURS[severity] ?? FALLBACK_COLOUR} />;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge text={status} colour={STATUS_COLOURS[status] ?? FALLBACK_COLOUR} />;
}

export function CaseStatusBadge({ status }: { status: string }) {
  return <Badge text={status.replaceAll("_", " ")} colour={CASE_STATUS_COLOURS[status] ?? FALLBACK_COLOUR} />;
}

export function EvidenceStatusBadge({ status }: { status: string }) {
  return <Badge text={status} colour={EVIDENCE_STATUS_COLOURS[status] ?? FALLBACK_COLOUR} />;
}

export function FindingStatusBadge({ status }: { status: string }) {
  return <Badge text={status.replaceAll("_", " ")} colour={FINDING_STATUS_COLOURS[status] ?? FALLBACK_COLOUR} />;
}
