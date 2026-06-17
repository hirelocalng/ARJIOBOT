type Props = { label: string; value: string | number; onChange: (value: string) => void };

export function NumberInput({ label, value, onChange }: Props) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-ink outline-none focus:border-action" type="number" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
