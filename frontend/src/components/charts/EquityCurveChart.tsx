import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

export function EquityCurveChart({ data }: { data: { timestamp: string; equity: string }[] }) {
  return (
    <div className="h-64 rounded-lg border border-slate-800 bg-panel p-3">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <XAxis dataKey="timestamp" hide />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
