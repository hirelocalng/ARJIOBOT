type Props = { title: string; message: string };

export function WarningCard({ title, message }: Props) {
  return (
    <div className="rounded-lg border border-warning/40 bg-warning/10 p-4">
      <div className="text-sm font-semibold text-warning">{title}</div>
      <div className="mt-1 text-sm text-slate-200">{message}</div>
    </div>
  );
}
