type Props = { label: string; value: string; type?: string; onChange: (value: string) => void; placeholder?: string };

export function TextInput({ label, value, type = 'text', onChange, placeholder }: Props) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <input className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-ink outline-none focus:border-action" type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}
