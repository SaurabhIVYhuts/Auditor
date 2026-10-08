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
