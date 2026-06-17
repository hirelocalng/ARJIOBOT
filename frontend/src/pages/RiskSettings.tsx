import { useEffect, useState } from 'react';
import { updateSettings } from '../api/settings';
import { NumberInput } from '../components/forms/NumberInput';
import type { ControlPlaneSnapshot } from '../types/controlPlane';
import type { BotSettings } from '../types/settings';

export function RiskSettings({ settings, onRefresh, controlPlane }: { settings: BotSettings | null; onRefresh: () => Promise<void>; controlPlane: ControlPlaneSnapshot | null }) {
  const [draft, setDraft] = useState({
    risk_amount_per_trade: settings?.risk_amount_per_trade ?? '100',
    max_leverage: settings?.max_leverage ?? '10',
    max_open_trades: settings?.max_open_trades ?? 1,
    max_daily_loss: settings?.max_daily_loss ?? '500',
    max_weekly_loss: settings?.max_weekly_loss ?? '1500',
    minimum_rr_ratio: settings?.minimum_rr_ratio ?? '0',
    min_position_size: settings?.min_position_size ?? '0',
    max_position_size: settings?.max_position_size ?? '1000000',
    max_symbol_exposure: settings?.max_symbol_exposure ?? '1000000'
  });
  const [saveStatus, setSaveStatus] = useState('SAVED');

  useEffect(() => {
    if (!settings) return;
    setDraft({
      risk_amount_per_trade: settings.risk_amount_per_trade ?? '100',
      max_leverage: settings.max_leverage ?? '10',
      max_open_trades: settings.max_open_trades ?? 1,
      max_daily_loss: settings.max_daily_loss ?? '500',
      max_weekly_loss: settings.max_weekly_loss ?? '1500',
      minimum_rr_ratio: settings.minimum_rr_ratio ?? '0',
      min_position_size: settings.min_position_size ?? '0',
      max_position_size: settings.max_position_size ?? '1000000',
      max_symbol_exposure: settings.max_symbol_exposure ?? '1000000'
    });
    setSaveStatus('SAVED');
  }, [settings]);

  function set(key: keyof typeof draft, value: string) {
    setDraft((current) => ({ ...current, [key]: key === 'max_open_trades' ? Number(value) : value }));
    setSaveStatus('UNSAVED');
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Risk Settings</h1>
      <div className="grid gap-3 md:grid-cols-4">
        <StatusCard label="Risk Lock" value={String(controlPlane?.active_risk_settings.risk_lock_status ?? 'FAILED')} />
        <StatusCard label="Save State" value={saveStatus} />
        <StatusCard label="Applied Fixed Risk" value={String(controlPlane?.active_risk_settings.fixed_risk_amount ?? settings?.risk_amount_per_trade ?? 'None')} />
        <StatusCard label="Applied Max Leverage" value={String(controlPlane?.active_risk_settings.max_leverage ?? settings?.max_leverage ?? 'None')} />
      </div>
      <div className="rounded-lg border border-action/30 bg-action/10 p-4 text-sm text-slate-200">Risk amount per trade is the maximum loss if stop loss is hit, not margin, leverage, or position size.</div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-3">
        <NumberInput label="Risk Amount Per Trade" value={draft.risk_amount_per_trade} onChange={(value) => set('risk_amount_per_trade', value)} />
        <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100">
          Applied TP model: {String(controlPlane?.active_strategy.applied_tp_model ?? settings?.selected_rr_profile ?? 'None')}
        </div>
        <NumberInput label="Max Leverage" value={draft.max_leverage} onChange={(value) => set('max_leverage', value)} />
        <NumberInput label="Max Open Trades" value={draft.max_open_trades} onChange={(value) => set('max_open_trades', value)} />
        <NumberInput label="Max Daily Loss" value={draft.max_daily_loss} onChange={(value) => set('max_daily_loss', value)} />
        <NumberInput label="Max Weekly Loss" value={draft.max_weekly_loss} onChange={(value) => set('max_weekly_loss', value)} />
        <NumberInput label="Minimum RR Ratio" value={draft.minimum_rr_ratio} onChange={(value) => set('minimum_rr_ratio', value)} />
        <NumberInput label="Min Position Size" value={draft.min_position_size} onChange={(value) => set('min_position_size', value)} />
        <NumberInput label="Max Position Size" value={draft.max_position_size} onChange={(value) => set('max_position_size', value)} />
        <NumberInput label="Max Symbol Exposure" value={draft.max_symbol_exposure} onChange={(value) => set('max_symbol_exposure', value)} />
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-muted md:col-span-3">
          Current active value comes from /api/control-plane. Pending unsaved changes are marked UNSAVED until Save Risk Settings succeeds.
        </div>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 md:col-span-3" onClick={async () => { setSaveStatus('APPLYING'); await updateSettings(draft); await onRefresh(); setSaveStatus('SAVED / APPLIED'); }}>Save Risk Settings</button>
      </div>
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-4"><div className="text-xs text-muted">{label}</div><div className="text-lg text-ink">{value}</div></div>;
}
