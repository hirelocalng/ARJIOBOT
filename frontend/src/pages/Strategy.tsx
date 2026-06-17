import { updateSettings } from '../api/settings';
import { SelectInput } from '../components/forms/SelectInput';
import type { ControlPlaneSnapshot } from '../types/controlPlane';
import type { BotSettings } from '../types/settings';
import { BACKTESTING_PROFILE_OPTIONS, PROFILE_FREEZE_WARNING, TIMEFRAME_PROFILES } from '../utils/constants';

export function Strategy({ controlPlane, settings, onRefresh }: { controlPlane: ControlPlaneSnapshot | null; settings: BotSettings | null; onRefresh: () => Promise<void> }) {
  const active = controlPlane?.active_strategy ?? {};
  const activeProfile = String(active.selected_profile ?? settings?.active_strategy_profile ?? settings?.default_backtesting_profile ?? BACKTESTING_PROFILE_OPTIONS[0].value);
  const timeframe = String(settings?.default_timeframe_profile ?? TIMEFRAME_PROFILES[0]);

  async function applyProfile(value: string) {
    await updateSettings({ active_strategy_profile: value, default_backtesting_profile: value });
    await onRefresh();
  }

  async function applyTimeframe(value: string) {
    await updateSettings({ default_timeframe_profile: value });
    await onRefresh();
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Strategy</h1>
        <p className="text-sm text-muted">Frozen profiles and allowed runtime selections. Strategy logic remains locked.</p>
      </div>
      <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">{PROFILE_FREEZE_WARNING}</div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-2">
        <SelectInput label="Active Strategy Profile" value={activeProfile} options={BACKTESTING_PROFILE_OPTIONS.map((item) => item.value)} onChange={(value) => void applyProfile(value)} />
        <SelectInput label="Active Timeframe Profile" value={timeframe} options={[...TIMEFRAME_PROFILES]} onChange={(value) => void applyTimeframe(value)} />
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Active Strategy Truth" rows={{
          selected_visible_profile: active.selected_profile,
          applied_to_engine_profile: active.visible_profile,
          profile_label: active.profile_label,
          profile_lock_status: active.profile_lock_status,
          profile_hash_freeze_status: active.profile_hash_freeze_status,
          strategy_ready: active.strategy_ready,
          saved_value: settings?.active_strategy_profile ?? 'None',
          selected_tp_model: active.selected_tp_model,
          saved_tp_model: active.saved_tp_model,
          applied_tp_model: active.applied_tp_model,
          override_allowed: active.tp_model_override_allowed,
          tp_model_lock_status: active.tp_model_lock_status,
          tp_model_lock_reason: active.tp_model_lock_reason,
        }} />
        <Panel title="Allowed Tunable Runtime Values" rows={{
          selected_timeframe_profile: timeframe,
          selected_rr_profile: settings?.selected_rr_profile ?? 'RR_1_5',
          fixed_risk_amount: settings?.risk_amount_per_trade ?? 'None',
          max_leverage: settings?.max_leverage ?? 'None',
          trade_mode: settings?.trading_mode ?? 'OFF',
        }} />
      </div>
    </div>
  );
}

function Panel({ title, rows }: { title: string; rows: Record<string, unknown> }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="mb-3 text-sm font-semibold text-ink">{title}</div>
      <div className="grid gap-2 text-sm">
        {Object.entries(rows).map(([key, value]) => (
          <div key={key} className="flex justify-between gap-3 border-b border-slate-800/70 pb-1 last:border-b-0">
            <span className="text-muted">{key}</span>
            <span className="text-right text-slate-100">{String(value ?? 'None')}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
