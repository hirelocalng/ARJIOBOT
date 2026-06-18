import { useEffect, useMemo, useState } from 'react';
import { NumberInput } from '../components/forms/NumberInput';
import { SelectInput } from '../components/forms/SelectInput';
import { dryRunPreview, runLiveAutomationOnce } from '../api/bitget';
import { testBitgetConnection } from '../api/accounts';
import type { ControlPlaneSnapshot } from '../types/controlPlane';

const LAST_PREVIEW_STORAGE_KEY = 'arjiobot:last-dry-run-preview';

export function TradingControlCenter({ controlPlane, onRefresh }: { controlPlane: ControlPlaneSnapshot | null; onRefresh: () => Promise<void> }) {
  if (!controlPlane) {
    return <div className="rounded-lg border border-slate-800 bg-panel p-4 text-sm text-muted">Loading unified control state...</div>;
  }

  return <LoadedTradingControlCenter controlPlane={controlPlane} onRefresh={onRefresh} />;
}

function LoadedTradingControlCenter({ controlPlane, onRefresh }: { controlPlane: ControlPlaneSnapshot; onRefresh: () => Promise<void> }) {
  const strategy = controlPlane.active_strategy;
  const exchange = controlPlane.active_exchange_mode;
  const account = controlPlane.active_account;
  const risk = controlPlane.active_risk_settings;
  const readiness = controlPlane.execution_readiness;
  const diagnostics = controlPlane.connection_diagnostics;
  const backtest = controlPlane.backtest_to_live_config;
  const trace = controlPlane.execution_pathway_trace;
  const setupDetection = controlPlane.live_setup_detection ?? {};
  const automation = controlPlane.live_automation ?? {};
  const backendPreviewStatus = controlPlane.last_order_preview ?? {};
  const backendPreview = asRecord(backendPreviewStatus.preview);
  const checklist = controlPlane.live_execution_readiness_checklist;
  const defaultSymbol = String(trace.pair_selected || controlPlane.active_pairs[0]?.symbol || 'BTCUSDT').toUpperCase();
  const [previewSymbol, setPreviewSymbol] = useState(defaultSymbol);
  const [previewSide, setPreviewSide] = useState('SELL');
  const selectedPair = controlPlane.active_pairs.find((pair) => pair.symbol === previewSymbol) ?? controlPlane.active_pairs.find((pair) => pair.symbol === defaultSymbol) ?? controlPlane.active_pairs[0];
  const livePrice = numericOrEmpty(selectedPair?.last_price);
  const maxLeverageValue = String(risk.max_leverage || controlPlane.settings.max_leverage || '1');
  const [previewEntry, setPreviewEntry] = useState(livePrice);
  const [previewStop, setPreviewStop] = useState('');
  const [previewTarget, setPreviewTarget] = useState('');
  const [previewStatus, setPreviewStatus] = useState('');
  const [previewResult, setPreviewResult] = useState<Record<string, unknown> | null>(() => readStoredPreview());
  const [automationStatus, setAutomationStatus] = useState('');
  const [connectionRefreshStatus, setConnectionRefreshStatus] = useState('');
  const [refreshingConnection, setRefreshingConnection] = useState(false);
  const selectedProfile = String(strategy.selected_profile || controlPlane.settings.active_strategy_profile || '');
  const selectedTpModel = String(strategy.applied_tp_model || controlPlane.settings.selected_rr_profile || 'RR_1_5');
  const timeExitEnabled = selectedTpModel === 'TIME_BASED_EXIT';
  const effectivePreview = Object.keys(backendPreview).length > 0 ? backendPreview : previewResult;
  const effectivePreviewStatus = Object.keys(backendPreview).length > 0
    ? backendPreviewStatus
    : previewResult
      ? {
          exists: 'YES',
          fresh: 'LOCAL',
          would_place_order: previewResult.would_place_order ?? 'NO',
          generated_at: previewResult.generated_at ?? 'Stored locally',
          message: 'Loaded saved diagnostic preview from this browser. Live automation still creates a fresh backend preview per real trade.',
        }
      : backendPreviewStatus;
  const previewPayload = useMemo(() => ({
    symbol: previewSymbol.toUpperCase(),
    side: previewSide,
    entry_price: previewEntry,
    stop_loss: previewStop,
    ...(timeExitEnabled ? {} : { take_profit: previewTarget }),
    selected_profile_id: selectedProfile,
    applied_profile_id: selectedProfile,
    profile_lock_status: String(strategy.profile_lock_status || 'FAILED'),
    selected_tp_model: selectedTpModel,
    applied_tp_model: selectedTpModel,
    time_exit_enabled: timeExitEnabled,
    time_exit_minutes: timeExitEnabled ? String(controlPlane.settings.time_exit_minutes || strategy.time_exit_minutes_applied || '') : '',
    planned_time_exit_at: timeExitEnabled ? plannedTimeExitAt(controlPlane.settings.time_exit_minutes || strategy.time_exit_minutes_applied) : '',
    time_exit_timer_starts_from: timeExitEnabled ? 'REAL_EXCHANGE_FILL_TIMESTAMP' : '',
    time_exit_close_type: timeExitEnabled ? 'MARKET' : '',
    risk_amount: String(risk.fixed_risk_amount || controlPlane.settings.risk_amount_per_trade || ''),
    selected_fixed_risk_amount: String(risk.fixed_risk_amount || controlPlane.settings.risk_amount_per_trade || ''),
    max_risk_per_trade: String(risk.fixed_risk_amount || controlPlane.settings.risk_amount_per_trade || ''),
    selected_max_leverage: maxLeverageValue,
    max_allowed_leverage: maxLeverageValue,
    max_daily_loss: String(risk.daily_loss_cap || controlPlane.settings.max_daily_loss || ''),
    max_trades_per_day: String(risk.max_trades_per_day || controlPlane.settings.max_open_trades || ''),
    max_open_positions: String(controlPlane.settings.max_open_trades || '1'),
    fee_rate: '0',
    slippage_rate: '0',
  }), [controlPlane.settings, maxLeverageValue, previewEntry, previewSide, previewStop, previewSymbol, previewTarget, risk, selectedProfile, selectedTpModel, strategy, timeExitEnabled]);

  const autoPreviewPrices = () => {
    const calculated = calculateSafePreviewPrices(livePrice || previewEntry, previewSide, maxLeverageValue);
    if (!calculated) {
      setPreviewStatus('Auto-fill blocked: live price or max leverage is missing.');
      return;
    }
    setPreviewEntry(calculated.entry);
    setPreviewStop(calculated.stop);
    setPreviewTarget(calculated.target);
    setPreviewStatus(`Auto-filled safe preview prices using ${calculated.requiredDistanceLabel} minimum stop distance.`);
  };

  useEffect(() => {
    if (livePrice) {
      const calculated = calculateSafePreviewPrices(livePrice, previewSide, maxLeverageValue);
      if (calculated) {
        setPreviewEntry(calculated.entry);
        setPreviewStop(calculated.stop);
        setPreviewTarget(calculated.target);
      }
    }
  }, [livePrice, maxLeverageValue, previewSide]);

  useEffect(() => {
    if (Object.keys(backendPreview).length > 0) {
      setPreviewResult(backendPreview);
      storePreview(backendPreview);
      setPreviewStatus(String(backendPreviewStatus.message ?? 'Loaded last backend dry-run preview.'));
    }
  }, [backendPreviewStatus.message, backendPreviewStatus.generated_at]);

  const runDryRunPreview = async () => {
    setPreviewStatus('Generating dry-run preview from backend...');
    setPreviewResult(null);
    try {
      const result = await dryRunPreview(previewPayload);
      setPreviewResult(result);
      storePreview(result);
      const blockedReason = String(result.blocked_reason ?? '');
      setPreviewStatus(
        String(result.would_place_order ?? 'NO') === 'YES'
          ? 'Dry-run preview created: would_place_order=YES'
          : `Dry-run preview blocked: ${blockedReason || 'backend did not approve the preview'}`
      );
      await onRefresh();
    } catch (error) {
      setPreviewStatus(`Dry-run preview failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const refreshControlState = async () => {
    setRefreshingConnection(true);
    setConnectionRefreshStatus('Testing Bitget connection...');
    try {
      const result = await testBitgetConnection();
      setConnectionRefreshStatus(
        result.connected
          ? `Connected (source: ${String(result.credential_source)}). Available balance: ${String(result.available_balance ?? 'N/A')}`
          : `Not connected (source: ${String(result.credential_source)}): ${String(result.error ?? 'unknown error')}`
      );
    } catch (error) {
      setConnectionRefreshStatus(`Connection test failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      await onRefresh();
      setRefreshingConnection(false);
    }
  };

  const runAutomationCheck = async () => {
    setAutomationStatus('Running live automation handoff check...');
    try {
      const result = await runLiveAutomationOnce();
      setAutomationStatus(`Automation result: ${String(result.status ?? 'UNKNOWN')} - ${String(result.reason ?? result.last_blocked_reason ?? 'None')}`);
      await onRefresh();
    } catch (error) {
      setAutomationStatus(`Automation check failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Trading Control Center</h1>
          <p className="text-sm text-muted">One backend source of truth for profile, exchange, mode, account, pairs, risk, readiness, and backtest-to-live transition.</p>
        </div>
        <button
          className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60"
          disabled={refreshingConnection}
          onClick={() => void refreshControlState()}
        >
          {refreshingConnection ? 'Testing connection...' : 'Refresh Control State'}
        </button>
      </div>

      {connectionRefreshStatus && (
        <div className={`rounded-md border p-3 text-xs ${connectionRefreshStatus.startsWith('Connected') ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100' : 'border-red-400/30 bg-red-500/10 text-red-100'}`}>
          {connectionRefreshStatus}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatusTile label="Profile Ready" value={readiness.profile_ready} />
        <StatusTile label="Exchange Ready" value={readiness.exchange_ready} />
        <StatusTile label="Account Ready" value={readiness.account_ready} />
        <StatusTile label="Pairs Monitoring" value={readiness.pairs_monitoring} />
        <StatusTile label="Risk Ready" value={readiness.risk_ready} />
        <StatusTile label="Execution Ready" value={readiness.execution_ready} strong />
      </div>

      {checklist && (
        <div className="rounded-lg border border-slate-800 bg-panel p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-ink">{checklist.title}</div>
              <div className="text-xs text-muted">Setup Radar source: {checklist.setup_radar_source}</div>
            </div>
            <Badge value={checklist.overall_status} />
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {Object.entries(checklist.checks).map(([name, record]) => (
              <div key={name} className="rounded-md border border-slate-800 bg-slate-950 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-slate-100">{name}</span>
                  <Badge value={record.ready} />
                </div>
                <div className="mt-2 text-xs text-muted">{record.reason}</div>
              </div>
            ))}
          </div>
          {checklist.blockers.length > 0 && (
            <div className="mt-3 rounded-md border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-100">
              {checklist.blockers.join(' | ')}
            </div>
          )}
        </div>
      )}

      <div className="rounded-lg border border-slate-800 bg-panel p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-ink">Dry-Run Order Preview</div>
            <div className="text-xs text-muted">Diagnostic only. Live automation builds a fresh backend preview when a real trade plan is ready.</div>
          </div>
          <Badge value={String(effectivePreview?.would_place_order ?? effectivePreviewStatus.would_place_order ?? 'NO')} />
        </div>
        <div className="mb-3 grid gap-2 md:grid-cols-4">
          <MiniRecord label="Preview Exists" value={effectivePreviewStatus.exists ?? 'NO'} />
          <MiniRecord label="Preview Source/Freshness" value={effectivePreviewStatus.fresh ?? 'NO'} />
          <MiniRecord label="Preview Message" value={effectivePreviewStatus.message ?? 'Manual preview is not required for automated execution.'} />
          <MiniRecord label="Last Generated" value={effectivePreviewStatus.generated_at ?? 'None'} />
        </div>
        <div className="grid gap-3 md:grid-cols-7">
          <SelectInput label="Symbol" value={previewSymbol} options={controlPlane.active_pairs.map((pair) => pair.symbol)} onChange={setPreviewSymbol} />
          <SelectInput label="Side" value={previewSide} options={['SELL', 'BUY']} onChange={setPreviewSide} />
          <NumberInput label="Entry Price" value={previewEntry} onChange={setPreviewEntry} />
          <NumberInput label="Stop Loss" value={previewStop} onChange={setPreviewStop} />
          <NumberInput label="Take Profit" value={previewTarget} onChange={setPreviewTarget} />
          <button
            className="mt-6 rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-slate-100 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
            disabled={!livePrice && !previewEntry}
            onClick={autoPreviewPrices}
          >
            Auto-Fill Safe Prices
          </button>
          <button
            className="mt-6 rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            disabled={!previewSymbol || !previewEntry || !previewStop}
            onClick={() => void runDryRunPreview()}
          >
            Generate Dry-Run Preview
          </button>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-4">
          <MiniRecord label="Selected Profile" value={selectedProfile} />
          <MiniRecord label="Applied Profile" value={selectedProfile} />
          <MiniRecord label="Fixed Risk" value={previewPayload.risk_amount} />
          <MiniRecord label="Max Leverage" value={previewPayload.selected_max_leverage} />
          <MiniRecord label="Auto Price Source" value={livePrice ? `${previewSymbol} live price` : 'Manual entry'} />
        </div>
        <div className={`mt-3 rounded-md border p-3 text-xs ${previewStatus.includes('failed') ? 'border-red-400/30 bg-red-500/10 text-red-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>
          {previewStatus || 'No dry-run preview generated yet.'}
        </div>
        {effectivePreview && (
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <Panel title="Preview Verification" rows={{
              would_place_order: effectivePreview.would_place_order,
              network_submitted: effectivePreview.network_submitted,
              exchange_lock_status: effectivePreview.exchange_lock_status,
              risk_lock_status: effectivePreview.risk_lock_status,
              profile_lock_status: effectivePreview.profile_lock_status,
              selected_trade_mode: effectivePreview.selected_trade_mode,
              selected_profile_id: effectivePreview.selected_profile_id,
              applied_profile_id: effectivePreview.applied_profile_id,
              size: effectivePreview.size,
              expected_loss_at_sl: effectivePreview.expected_loss_at_sl,
              expected_profit_at_tp: effectivePreview.expected_profit_at_tp,
              blocked_reason: effectivePreview.blocked_reason,
            }} />
            <Panel title="Sanitized Bitget Payload" rows={asRecord(effectivePreview.sanitized_payload)} />
          </div>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Active Strategy" rows={{
          selected_visible_profile: strategy.selected_profile,
          profile_label: strategy.profile_label,
          profile_lock_status: strategy.profile_lock_status,
          profile_hash_freeze_status: strategy.profile_hash_freeze_status,
          strategy_ready: strategy.strategy_ready,
          selected_tp_model: strategy.selected_tp_model,
          saved_tp_model: strategy.saved_tp_model,
          applied_tp_model: strategy.applied_tp_model,
          override_allowed: strategy.tp_model_override_allowed,
          tp_model_lock_status: strategy.tp_model_lock_status,
          current_active_value: strategy.selected_profile,
          saved_value: controlPlane.settings.active_strategy_profile,
          applied_to_engine_value: strategy.visible_profile,
        }} />
        <Panel title="Active Exchange + Mode" rows={{
          selected_exchange: exchange.selected_exchange,
          adapter_mode: exchange.adapter_mode,
          selected_trade_mode: exchange.selected_trade_mode,
          active_execution_mode: exchange.active_execution_mode,
          exchange_lock_status: exchange.exchange_lock_status,
          environment_lock_status: exchange.environment_lock_status,
          environment_lock_verified: exchange.environment_lock_verified,
        }} />
        <Panel title="Active Account" rows={{
          connected_account: account.account_name,
          account_id: account.account_id,
          connection_status: account.connection_status,
          credential_type: account.credential_type,
          last_successful_api_ping_time: account.last_successful_api_ping_time,
          balance: account.balance,
          margin_mode_confirmation: account.margin_mode_confirmation,
          leverage_support_confirmation: account.leverage_support_confirmation,
          endpoint_reachable: account.endpoint_reachable,
        }} />
        <Panel title="Active Risk Settings" rows={{
          starting_balance: risk.starting_balance,
          fixed_risk_amount: risk.fixed_risk_amount,
          trade_type: risk.trade_type,
          margin_amount: risk.margin_amount,
          max_leverage: risk.max_leverage,
          daily_loss_cap: risk.daily_loss_cap,
          max_trades_per_day: risk.max_trades_per_day,
          kill_switch_status: risk.kill_switch_status,
          risk_lock_status: risk.risk_lock_status,
        }} />
        <Panel title="Backtest-To-Live Config" rows={{
          status: backtest.status,
          last_profitable_profile: backtest.last_profitable_profile,
          profitable_risk_setting: backtest.profitable_risk_setting,
          profitable_leverage_setting: backtest.profitable_leverage_setting,
          profitable_pair: backtest.profitable_pair,
          profitable_timeframe_stack: backtest.profitable_timeframe_stack,
          average_time_to_tp: backtest.average_time_to_tp,
          currently_active_in_live: backtest.currently_active_in_live,
        }} />
        <Panel title="Connection Diagnostics" rows={{
          api_credentials_present: diagnostics.api_credentials_present,
          connection_test_passed: diagnostics.connection_test_passed,
          account_fetched: diagnostics.account_fetched,
          pair_subscription_active: diagnostics.pair_subscription_active,
          live_mode_locked: diagnostics.live_mode_locked,
          last_error: diagnostics.last_error,
          last_successful_heartbeat: diagnostics.last_successful_heartbeat,
        }} />
      </div>

      <div className="rounded-lg border border-slate-800 bg-panel p-4">
        <div className="mb-3 text-sm font-semibold text-ink">Active Pairs</div>
        <div className="overflow-auto">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="text-left text-xs uppercase text-muted">
              <tr>{['Pair', 'Detected', 'Stream', 'Last Price', 'Last Update', 'Monitoring', 'Timeframes', 'Error'].map((header) => <th key={header} className="px-2 py-2 font-medium">{header}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {controlPlane.active_pairs.map((pair) => (
                <tr key={pair.symbol}>
                  <td className="px-2 py-2 text-slate-100">{pair.symbol}</td>
                  <td className="px-2 py-2"><Badge value={pair.detected_by_exchange} /></td>
                  <td className="px-2 py-2"><Badge value={pair.market_data_stream_active} /></td>
                  <td className="px-2 py-2 text-slate-100">{pair.last_price}</td>
                  <td className="px-2 py-2 text-slate-100">{pair.last_price_update_time}</td>
                  <td className="px-2 py-2"><Badge value={pair.monitoring_status} /></td>
                  <td className="px-2 py-2 text-slate-100">{pair.active_timeframes.join(', ')}</td>
                  <td className="px-2 py-2 text-slate-100">{pair.last_error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Panel title="Execution Pathway Trace" rows={{
        pair_selected: trace.pair_selected,
        stream_active: trace.stream_active,
        signal_engine_active: trace.signal_engine_active,
        live_setup_detection_status: trace.live_setup_detection_status,
        live_setup_detection_last_blocked_reason: trace.live_setup_detection_last_blocked_reason,
        signal_generated: trace.signal_generated,
        trade_plan_created: trace.trade_plan_created,
        live_automation_status: trace.live_automation_status,
        live_automation_last_blocked_reason: trace.live_automation_last_blocked_reason,
        execution_eligible: trace.execution_eligible,
        blocked_reason: trace.blocked_reason,
      }} />

      <Panel title="Live Candle-To-Setup Detection" rows={{
        last_run_at: setupDetection.last_run_at,
        last_status: setupDetection.last_status,
        last_blocked_reason: setupDetection.last_blocked_reason,
        last_error: setupDetection.last_error,
        created_setup_count: setupDetection.created_setup_count,
        latest_funnel: JSON.stringify(setupDetection.latest_funnel ?? {}),
        latest_trade_candidate: JSON.stringify(setupDetection.latest_trade_candidate ?? {}),
      }} />

      <div className="rounded-lg border border-slate-800 bg-panel p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-ink">Live Automation Handoff</div>
            <div className="text-xs text-muted">Runs the backend setup-to-signal-to-risk-to-Bitget handoff once. Automatic checks also run after monitoring polls.</div>
          </div>
          <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void runAutomationCheck()}>
            Run Automation Check Now
          </button>
        </div>
        {automationStatus && (
          <div className="mb-3 rounded-md border border-slate-700 bg-slate-950 p-3 text-xs text-slate-100">{automationStatus}</div>
        )}
        <RecordGrid rows={{
          enabled: automation.enabled,
          last_run_at: automation.last_run_at,
          last_status: automation.last_status,
          last_blocked_reason: automation.last_blocked_reason,
          last_error: automation.last_error,
          processed_setup_count: automation.processed_setup_count,
          executed_trade_plan_count: automation.executed_trade_plan_count,
          latest_attempt: JSON.stringify(automation.latest_attempt ?? {}),
        }} />
      </div>
    </div>
  );
}

function MiniRecord({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-100">{String(value ?? 'None')}</div>
    </div>
  );
}

function numericOrEmpty(value: unknown) {
  const text = String(value ?? '');
  return Number.isFinite(Number(text)) && Number(text) > 0 ? text : '';
}

function plannedTimeExitAt(minutesValue: unknown) {
  const minutes = Number(String(minutesValue ?? ''));
  if (!Number.isFinite(minutes) || minutes <= 0) return '';
  return new Date(Date.now() + minutes * 60_000).toISOString();
}

function calculateSafePreviewPrices(priceValue: string, side: string, maxLeverageValue: string) {
  const entry = Number(priceValue);
  const maxLeverage = Number(maxLeverageValue);
  if (!Number.isFinite(entry) || entry <= 0 || !Number.isFinite(maxLeverage) || maxLeverage <= 0) return null;

  const minimumDistance = entry / maxLeverage;
  const safetyDistance = minimumDistance * 1.2;
  const targetDistance = safetyDistance * 1.5;
  const normalizedSide = side.toUpperCase();
  const stop = normalizedSide === 'BUY' ? entry - safetyDistance : entry + safetyDistance;
  const target = normalizedSide === 'BUY' ? entry + targetDistance : entry - targetDistance;
  if (stop <= 0 || target <= 0) return null;

  return {
    entry: formatPreviewPrice(entry),
    stop: formatPreviewPrice(stop),
    target: formatPreviewPrice(target),
    requiredDistanceLabel: formatPreviewPrice(safetyDistance),
  };
}

function formatPreviewPrice(value: number) {
  const decimals = value >= 1000 ? 2 : value >= 1 ? 4 : 6;
  return value.toFixed(decimals);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readStoredPreview(): Record<string, unknown> | null {
  try {
    const raw = window.localStorage.getItem(LAST_PREVIEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function storePreview(preview: Record<string, unknown>) {
  try {
    window.localStorage.setItem(LAST_PREVIEW_STORAGE_KEY, JSON.stringify(preview));
  } catch {
    // Local storage is best-effort; backend state remains authoritative.
  }
}

function Panel({ title, rows }: { title: string; rows: Record<string, unknown> }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-panel p-4">
      <div className="mb-3 text-sm font-semibold text-ink">{title}</div>
      <RecordGrid rows={rows} />
    </div>
  );
}

function RecordGrid({ rows }: { rows: Record<string, unknown> }) {
  return (
    <div className="grid gap-2 text-sm">
      {Object.entries(rows).map(([key, value]) => (
        <div key={key} className="flex justify-between gap-3 border-b border-slate-800/70 pb-1 last:border-b-0">
          <span className="text-muted">{key}</span>
          <span className="break-words text-right text-slate-100">{String(value ?? 'None')}</span>
        </div>
      ))}
    </div>
  );
}

function StatusTile({ label, value, strong = false }: { label: string; value: unknown; strong?: boolean }) {
  return (
    <div className={`rounded-lg border p-4 ${strong ? 'border-action/40 bg-action/10' : 'border-slate-800 bg-panel'}`}>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1"><Badge value={String(value ?? 'NO')} /></div>
    </div>
  );
}

function Badge({ value }: { value: string }) {
  const normalized = value.toUpperCase();
  const positive = ['YES', 'PASSED', 'CONNECTED', 'ACTIVE', 'READY', 'SAVED', 'APPLIED', 'FROZEN'].includes(normalized);
  const negative = ['NO', 'FAILED', 'ERROR', 'BLOCKED', 'NOT CONNECTED', 'NOT ACTIVE', 'NOT MONITORING', 'NOT APPLIED'].includes(normalized);
  const className = positive
    ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-100'
    : negative
      ? 'border-red-400/40 bg-red-500/10 text-red-100'
      : 'border-slate-600 bg-slate-800 text-slate-100';
  return <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${className}`}>{value}</span>;
}
