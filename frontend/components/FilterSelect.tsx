import { label } from "@/lib/format";

/** A list-filter dropdown with an "All" choice (value ""). */
export function FilterSelect({ name, value, options, onChange }: {
  name: string; value: string; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <label style={{ marginRight: 12 }}>
      {name}:{" "}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>{label(o)}</option>
        ))}
      </select>
    </label>
  );
}
