export const formatPercent = (value: number) => `${value.toFixed(0)}%`;
export const formatMoney = (value?: string | number) => (value == null ? '—' : `${value} USDT`);
export const compactId = (value?: string) => (value ? `${value.slice(0, 8)}…${value.slice(-4)}` : '—');
