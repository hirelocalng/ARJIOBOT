import { useState } from 'react';
import { addPair, importPairs, removePair, startMonitoring, stopMonitoring, updatePair } from '../api/pairs';
import { TextInput } from '../components/forms/TextInput';
import { Toggle } from '../components/forms/Toggle';
import { DataTable } from '../components/tables/DataTable';
import type { ControlPlaneSnapshot } from '../types/controlPlane';
import type { MonitoredPair } from '../types/pairs';
import { confirmDangerousAction } from '../utils/safety';

export function PairManager({ pairs, onRefresh, controlPlane }: { pairs: MonitoredPair[]; onRefresh: () => Promise<void>; controlPlane: ControlPlaneSnapshot | null }) {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [bulk, setBulk] = useState('ETHUSDT,SOLUSDT,XRPUSDT');
  const [status, setStatus] = useState('Monitoring not started');

  async function start() {
    try {
      setStatus('Starting real Bitget monitoring...');
      await startMonitoring();
      setStatus('MONITORING STARTED - live market polling in progress');
      window.alert('MONITORING STARTED - live market polling in progress');
      await onRefresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Monitoring failed';
      setStatus(`MONITORING FAILED: ${message}`);
      window.alert(`MONITORING FAILED: ${message}`);
      await onRefresh();
    }
  }

  async function stop() {
    await stopMonitoring();
    setStatus('MONITORING STOPPED');
    window.alert('MONITORING STOPPED');
    await onRefresh();
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Markets/Pairs</h1>
      <div className="grid gap-3 md:grid-cols-3">
        <StatusCard label="Pair Monitoring" value={String(controlPlane?.execution_readiness.pairs_monitoring ?? 'NO')} />
        <StatusCard label="Selected Exchange" value={String(controlPlane?.active_exchange_mode.selected_exchange ?? 'BITGET')} />
        <StatusCard label="Timeframe Feeds" value={String(controlPlane?.active_pairs.some((pair) => pair.timeframe_subscription_status === 'ACTIVE') ? 'ACTIVE' : 'NOT ACTIVE')} />
      </div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-3">
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void start()}>START MONITORING</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-slate-100" onClick={() => void stop()}>STOP MONITORING</button>
        <div className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100">{status}</div>
      </div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-3">
        <TextInput label="Symbol" value={symbol} onChange={setSymbol} />
        <button className="self-end rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={async () => { await addPair(symbol); await onRefresh(); }}>Add Pair</button>
        <TextInput label="Import Pairs" value={bulk} onChange={setBulk} />
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm text-ink md:col-span-3" onClick={async () => { await importPairs(bulk.split(',').map((item) => item.trim())); await onRefresh(); }}>Import Multiple</button>
      </div>
      {String(controlPlane?.active_exchange_mode.mock_mode_warning ?? 'None') !== 'None' ? (
        <div className="rounded-lg border border-amber-600/40 bg-amber-950/30 px-4 py-3 text-sm text-amber-100">
          {String(controlPlane?.active_exchange_mode.mock_mode_warning)}
        </div>
      ) : null}
      <DataTable
        rows={pairs}
        emptyLabel="NO PAIRS CONFIGURED FOR REAL MONITORING"
        columns={[
          { header: 'Symbol', render: (row) => row.symbol },
          { header: 'Enabled', render: (row) => <Toggle label="" checked={row.enabled} onChange={async (checked) => { await updatePair(row.symbol, checked); await onRefresh(); }} /> },
          { header: 'Detected', render: (row) => controlPair(controlPlane, row.symbol)?.detected_by_exchange ?? 'NO' },
          { header: 'Contract', render: (row) => controlPair(controlPlane, row.symbol)?.contract_config_loaded ?? 'NO' },
          { header: 'Monitoring', render: (row) => controlPair(controlPlane, row.symbol)?.monitoring_status ?? 'NOT ACTIVE' },
          { header: 'Stream', render: (row) => controlPair(controlPlane, row.symbol)?.market_data_stream_active ?? 'NO' },
          { header: 'Last Price', render: (row) => controlPair(controlPlane, row.symbol)?.last_price ?? 'None' },
          { header: 'Bid', render: (row) => controlPair(controlPlane, row.symbol)?.bid_price ?? 'N/A' },
          { header: 'Ask', render: (row) => controlPair(controlPlane, row.symbol)?.ask_price ?? 'N/A' },
          { header: 'Mark', render: (row) => controlPair(controlPlane, row.symbol)?.mark_price ?? 'N/A' },
          { header: '1M Candles', render: (row) => String(controlPair(controlPlane, row.symbol)?.live_candle_count ?? 0) },
          { header: 'Last Tick', render: (row) => controlPair(controlPlane, row.symbol)?.last_price_update_time ?? 'None' },
          { header: 'Next Refresh', render: (row) => controlPair(controlPlane, row.symbol)?.next_scheduled_refresh_time ?? 'N/A' },
          { header: 'Last Error', render: (row) => controlPair(controlPlane, row.symbol)?.last_error ?? 'None' },
          { header: 'Timeframes', render: (row) => controlPair(controlPlane, row.symbol)?.active_timeframes?.join(', ') ?? 'None' },
          { header: 'Action', render: (row) => <button className="text-danger" onClick={async () => { if (confirmDangerousAction(`Delete ${row.symbol}?`)) { await removePair(row.symbol); await onRefresh(); } }}>Delete</button> }
        ]}
      />
    </div>
  );
}

function controlPair(controlPlane: ControlPlaneSnapshot | null, symbol: string) {
  return controlPlane?.active_pairs.find((pair) => pair.symbol === symbol);
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-4"><div className="text-xs text-muted">{label}</div><div className="text-lg text-ink">{value}</div></div>;
}
