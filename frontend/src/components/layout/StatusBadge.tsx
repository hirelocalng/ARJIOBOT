type Props = { label: string; tone?: 'ok' | 'warn' | 'danger' | 'neutral' };

export function StatusBadge({ label, tone = 'neutral' }: Props) {
  const tones = {
    ok: 'border-success/40 bg-success/10 text-success',
    warn: 'border-warning/40 bg-warning/10 text-warning',
    danger: 'border-danger/40 bg-danger/10 text-danger',
    neutral: 'border-slate-600 bg-slate-800 text-slate-200'
  };
  return <span className={`inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium ${tones[tone]}`}>{label}</span>;
}
