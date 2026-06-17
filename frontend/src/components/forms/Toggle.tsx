type Props = { label: string; checked: boolean; onChange: (checked: boolean) => void };

export function Toggle({ label, checked, onChange }: Props) {
  return (
    <label className="flex items-center justify-between rounded-md border border-slate-800 bg-panel px-3 py-2 text-sm text-slate-200">
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}
