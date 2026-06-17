type Props = { label: string; value: number };

export function ProgressCard({ label, value }: Props) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="flex justify-between text-sm">
        <span className="text-muted">{label}</span>
        <span className="text-ink">{value.toFixed(0)}%</span>
      </div>
      <div className="mt-3 h-2 rounded bg-slate-800">
        <div className="h-2 rounded bg-action" style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  );
}
