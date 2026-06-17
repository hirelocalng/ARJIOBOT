import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const DATA = [
  { metric: 'Wins', value: 0 },
  { metric: 'Losses', value: 0 },
  { metric: 'Trades', value: 0 }
];

export function PerformanceChart() {
  return (
    <div className="h-56 rounded-lg border border-slate-800 bg-panel p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={DATA}>
          <XAxis dataKey="metric" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="value" fill="#f59e0b" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
