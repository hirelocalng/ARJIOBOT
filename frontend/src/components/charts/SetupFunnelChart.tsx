import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const FUNNEL = [
  { name: '30%', value: 8 },
  { name: '50%', value: 6 },
  { name: '70%', value: 4 },
  { name: '90%', value: 2 },
  { name: 'Entry', value: 1 }
];

export function SetupFunnelChart() {
  return (
    <div className="h-64 rounded-lg border border-slate-800 bg-panel p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={FUNNEL}>
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="value" fill="#22c55e" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
