import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { switchBitgetMode, type TradingMode } from '../api/bitget';
import { emergencyStop, getMobileControlStatus, type MobileControlStatus } from '../api/mobile';
import { updateSettings } from '../api/settings';
import type { ExecutionRecord } from '../types/execution';
import type { TradePlan } from '../types/risk';
import type { BotSettings } from '../types/settings';
import { PROFILE_FREEZE_WARNING } from '../utils/constants';

export function MobileControl({
  settings,
  plans,
  executions,
  onRefresh,
}: {
  settings: BotSettings | null;
  plans: TradePlan[];
  executions: ExecutionRecord[];
  onRefresh: () => Promise<void>;
}) {
  const [control, setControl] = useState<MobileControlStatus | null>(null);
  const [riskAmount, setRiskAmount] = useState(settings?.risk_amount_per_trade ?? '');
  const [maxLeverage, setMaxLeverage] = useState(settings?.max_leverage ?? '');
  const [startingBalance, setStartingBalance] = useState(settings?.starting_balance ?? '');
  const [liveConfirmation, setLiveConfirmation] = useState('');
  const [status, setStatus] = useState('Ready');

  async function refreshControl() {
    const next = await getMobileControlStatus();
    setControl(next);
  }

  useEffect(() => {
    void refreshControl().catch(() => setStatus('Mobile status unavailable'));
  }, []);

  useEffect(() => {
    setRiskAmount(settings?.risk_amount_per_trade ?? '');
    setMaxLeverage(settings?.max_leverage ?? '');
    setStartingBalance(settings?.starting_balance ?? '');
  }, [settings]);

  async function applyMode(mode: TradingMode) {
    try {
      setStatus(`Switching to ${mode}...`);
      await switchBitgetMode(mode, liveConfirmation);
      await onRefresh();
      await refreshControl();
      setStatus(`Trading mode: ${mode}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Mode switch failed');
    }
  }

  async function saveRisk() {
    try {
      setStatus('Saving risk controls...');
      await updateSettings({ starting_balance: startingBalance, risk_amount_per_trade: riskAmount, max_leverage: maxLeverage });
      await onRefresh();
      await refreshControl();
      setStatus('Risk controls saved');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Risk save failed');
    }
  }

  async function stopNow() {
    try {
      setStatus('Emergency stop engaging...');
      await emergencyStop();
      await onRefresh();
      await refreshControl();
      setStatus('Emergency stop engaged. Server trading mode is OFF.');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Emergency stop failed');
    }
  }

  const openExecutions = executions.filter((execution) => !['CANCELLED', 'FAILED', 'FILLED', 'REJECTED'].includes(String(execution.status ?? '').toUpperCase()));

  return (
    <div className="space-y-3 pb-20">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-ink">Mobile Control</h1>
        <button className="min-h-11 rounded-md bg-slate-800 px-3 py-2 text-sm text-slate-100" onClick={() => void refreshControl()}>Refresh</button>
      </div>

      <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">{PROFILE_FREEZE_WARNING}</div>

      <section className="rounded-lg border border-red-400/50 bg-red-500/10 p-3">
        <div className="text-sm font-semibold text-red-100">Emergency Stop</div>
        <div className="mt-1 text-xs text-red-100/80">Switches the VPS trading mode to OFF. The phone is only a control dashboard.</div>
        <button className="mt-3 min-h-14 w-full rounded-md bg-red-500 px-4 py-3 text-base font-bold text-white" onClick={() => void stopNow()}>
          EMERGENCY STOP
        </button>
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <Panel title="Trade Mode">
          <div className="grid grid-cols-3 gap-2">
            {(['OFF', 'DRY_RUN_PREVIEW', 'LIVE'] as TradingMode[]).map((mode) => (
              <button
                key={mode}
                className={`min-h-12 rounded-md px-2 text-sm font-semibold ${control?.trading_mode === mode ? 'bg-action text-slate-950' : 'bg-slate-800 text-slate-100'}`}
                onClick={() => void applyMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
          <input className="mt-3 min-h-11 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm" value={liveConfirmation} onChange={(event) => setLiveConfirmation(event.target.value)} placeholder="ENABLE LIVE" />
        </Panel>

        <Panel title="Selected Profile">
          <div className="text-base font-semibold text-action">{control?.selected_profile ?? settings?.active_strategy_profile ?? 'PROFILE_RECOVERED_HIGH_WINRATE'}</div>
          <div className="mt-2 text-xs text-muted">Visible profile: {control?.visible_profile ?? 'PROFILE_RECOVERED_HIGH_WINRATE'}</div>
          <div className="mt-2 text-xs text-muted">Server role: {control?.engine_host ?? 'VPS_SERVER'}</div>
        </Panel>
      </section>

      <Panel title="Risk / Margin Controls">
        <div className="grid gap-2 sm:grid-cols-3">
          <MobileInput label="Starting Balance" value={startingBalance} onChange={setStartingBalance} />
          <MobileInput label="Fixed Risk" value={riskAmount} onChange={setRiskAmount} />
          <MobileInput label="Max Leverage" value={maxLeverage} onChange={setMaxLeverage} />
        </div>
        <button className="mt-3 min-h-12 w-full rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void saveRisk()}>Save Risk Controls</button>
      </Panel>

      <section className="grid gap-3 sm:grid-cols-3">
        <Metric label="Mode" value={control?.trading_mode ?? settings?.trading_mode ?? 'OFF'} />
        <Metric label="Trade Plans" value={control?.trade_plans_count ?? plans.length} />
        <Metric label="Open Positions" value={control?.open_positions_count ?? openExecutions.length} />
      </section>

      <Panel title="Trade Status">
        <Rows rows={plans.slice(0, 5).map((plan) => ({
          left: String(plan.trade_plan_id ?? 'plan'),
          right: String(plan.approval_status ?? 'pending'),
        }))} empty="No trade plans." />
      </Panel>

      <Panel title="Open Positions">
        <Rows rows={openExecutions.slice(0, 5).map((execution) => ({
          left: String(execution.execution_id ?? 'execution'),
          right: String(execution.status ?? 'open'),
        }))} empty="No open positions." />
      </Panel>

      <Panel title="Logs">
        <Rows rows={(control?.recent_logs ?? []).slice().reverse().map((log, index) => ({
          left: String(log.mode ?? log.trading_mode ?? `log ${index + 1}`),
          right: String(log.timestamp ?? log.created_at ?? log.status ?? ''),
        }))} empty="No recent mode logs." />
      </Panel>

      <div className="rounded-lg border border-slate-800 bg-panel p-3 text-sm text-slate-200">Status: {status}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rounded-lg border border-slate-800 bg-panel p-3"><div className="mb-3 text-xs uppercase text-muted">{title}</div>{children}</section>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-3"><div className="text-xs text-muted">{label}</div><div className="mt-1 text-lg font-semibold text-ink">{String(value)}</div></div>;
}

function MobileInput({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="text-muted">{label}</span>
      <input className="min-h-11 rounded-md border border-slate-700 bg-slate-950 px-3 text-slate-100" value={value} onChange={(event) => onChange(event.target.value)} inputMode="decimal" />
    </label>
  );
}

function Rows({ rows, empty }: { rows: { left: string; right: string }[]; empty: string }) {
  if (!rows.length) return <div className="text-sm text-muted">{empty}</div>;
  return (
    <div className="grid gap-2">
      {rows.map((row, index) => (
        <div key={`${row.left}-${index}`} className="flex min-h-10 items-center justify-between gap-3 rounded-md bg-slate-950 px-3 py-2 text-sm">
          <span className="break-all text-slate-100">{row.left}</span>
          <span className="shrink-0 text-muted">{row.right}</span>
        </div>
      ))}
    </div>
  );
}
