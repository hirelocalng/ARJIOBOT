type Props = { label: string; value: string | number; detail?: string };

export function MetricCard({ label, value, detail }: Props) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
      {detail && <div className="mt-1 text-xs text-slate-400">{detail}</div>}
    </div>
  );
}
