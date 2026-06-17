export function SetupProgressBar({ value }: { value: number }) {
  const tone = value >= 90 ? 'bg-success' : value >= 70 ? 'bg-warning' : 'bg-action';
  return (
    <div className="h-2 w-32 rounded bg-slate-800">
      <div className={`h-2 rounded ${tone}`} style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  );
}
