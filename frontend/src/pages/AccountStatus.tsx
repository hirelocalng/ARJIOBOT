import { useEffect, useState } from 'react';
import {
  getAccountLeverageStatus,
  getAccountMarginModeStatus,
  getAccountOpenOrdersStatus,
  getAccountPositionsStatus,
  getAccountStatusSummary,
  refreshAccountStatus
} from '../api/accountStatus';
import type { AccountStatusSummary } from '../types/accountStatus';

const EMPTY_SUMMARY: AccountStatusSummary = {
  account_connection: {},
  balance: {},
  margin_mode: {},
  position_mode: {},
  order_type_price_type: {},
  leverage: {},
  open_positions: { status: 'WAITING', position_count: 0, positions: [] },
  open_orders: { status: 'WAITING', order_count: 0, orders: [] },
  risk_status: {},
  data_freshness: {}
};

export function AccountStatus({ onRefresh }: { onRefresh: () => Promise<void> }) {
  const [summary, setSummary] = useState<AccountStatusSummary>(EMPTY_SUMMARY);
  const [status, setStatus] = useState('Loading account status...');

  async function load() {
    try {
      const next = await getAccountStatusSummary();
      setSummary(next);
      setStatus('Account status loaded');
    } catch (error) {
      setStatus(error instanceof Error ? `Account status unavailable: ${error.message}` : 'Account status unavailable');
    }
  }

  async function runAction(label: string, action: () => Promise<unknown>) {
    try {
      setStatus(`${label}...`);
      await action();
      await load();
      await onRefresh();
      setStatus(`${label} complete`);
    } catch (error) {
      setStatus(error instanceof Error ? `${label} failed: ${error.message}` : `${label} failed`);
      await load();
    }
  }

  useEffect(() => {
    void refreshOnOpen();
  }, []);

  async function refreshOnOpen() {
    try {
      setStatus('Refreshing account status...');
      const next = await refreshAccountStatus();
      setSummary(next);
      setStatus('Account status refreshed');
      await onRefresh();
    } catch (error) {
      await load();
      setStatus(error instanceof Error ? `Account refresh unavailable: ${error.message}` : 'Account refresh unavailable');
    }
  }

  const positions = Array.isArray(summary.open_positions.positions) ? summary.open_positions.positions : [];
  const orders = Array.isArray(summary.open_orders.orders) ? summary.open_orders.orders : [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Account Status</h1>
        <p className="text-sm text-muted">Real Bitget Futures account health and active execution settings.</p>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <StatusCard label="Connection" value={text(summary.account_connection.connection_status, 'NOT CONNECTED')} />
        <StatusCard label="Auth" value={text(summary.account_connection.private_api_auth_status, 'NOT CONFIRMED')} />
        <StatusCard label="Balance" value={text(summary.balance.available_balance, 'N/A')} />
        <StatusCard label="Risk" value={text(summary.risk_status.live_execution_status, 'BLOCKED')} />
        <StatusCard label="Freshness" value={text(summary.data_freshness.account_data_status, 'ACCOUNT DATA STALE')} />
      </div>

      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-5">
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => runAction('Refresh Account Status', refreshAccountStatus)}>Refresh Account Status</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-ink" onClick={() => runAction('Verify Margin Mode', getAccountMarginModeStatus)}>Verify Margin Mode</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-ink" onClick={() => runAction('Verify Leverage', getAccountLeverageStatus)}>Verify Leverage</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-ink" onClick={() => runAction('Refresh Positions', getAccountPositionsStatus)}>Refresh Positions</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-ink" onClick={() => runAction('Refresh Open Orders', getAccountOpenOrdersStatus)}>Refresh Open Orders</button>
        <div className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-ink md:col-span-5">{status}</div>
      </div>

      <Section title="Account Connection" record={summary.account_connection} />
      <div className="grid gap-5 xl:grid-cols-2">
        <Section title="Balance" record={summary.balance} />
        <Section title="Data Freshness" record={summary.data_freshness} />
        <Section title="Margin Mode" record={summary.margin_mode} />
        <Section title="Position Mode" record={summary.position_mode} />
        <Section title="Order Type / Price Type" record={summary.order_type_price_type} />
        <Section title="Leverage" record={summary.leverage} />
        <Section title="Risk Status" record={summary.risk_status} />
      </div>

      <Rows title="Open Positions" status={summary.open_positions.status ?? 'WAITING'} rows={positions} emptyLabel="NO OPEN POSITIONS" />
      <Rows title="Open Orders" status={summary.open_orders.status ?? 'WAITING'} rows={orders} emptyLabel="NO OPEN ORDERS" />
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-lg text-ink">{value}</div>
    </div>
  );
}

function Section({ title, record }: { title: string; record: Record<string, unknown> }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-panel p-4">
      <h2 className="mb-3 text-base font-semibold text-ink">{title}</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Object.entries(record).length === 0 ? <Field label="status" value="WAITING" /> : Object.entries(record).map(([key, value]) => <Field key={key} label={key} value={formatValue(value)} />)}
      </div>
    </section>
  );
}

function Rows({ title, status, rows, emptyLabel }: { title: string; status: string; rows: Record<string, unknown>[]; emptyLabel: string }) {
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 10);
  return (
    <section className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <span className="rounded border border-slate-700 px-2 py-1 text-xs text-muted">{status}</span>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-3 text-sm text-muted">{emptyLabel}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>{keys.map((key) => <th className="border-b border-slate-800 px-3 py-2" key={key}>{key}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-b border-slate-800">
                  {keys.map((key) => <td className="px-3 py-2 text-ink" key={key}>{formatValue(row[key])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2">
      <div className="text-xs text-muted">{label}</div>
      <div className="break-words text-sm text-ink">{value}</div>
    </div>
  );
}

function text(value: unknown, fallback: string) {
  const formatted = formatValue(value);
  return formatted || fallback;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'N/A';
  if (Array.isArray(value)) return value.length ? value.map((item) => formatValue(item)).join(', ') : 'None';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
