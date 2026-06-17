type SelectOption = string | { value: string; label: string };
type Props = { label: string; value: string; options: SelectOption[]; onChange: (value: string) => void };

export function SelectInput({ label, value, options, onChange }: Props) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <select className="mt-1 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-ink outline-none focus:border-action" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => {
          const value = typeof option === 'string' ? option : option.value;
          const label = typeof option === 'string' ? option : option.label;
          return <option key={value} value={value}>{label}</option>;
        })}
      </select>
    </label>
  );
}
