import { useEffect, useState } from 'react';
import { getBacktestRun, runBacktest, uploadCsv } from '../api/backtesting';
import { EquityCurveChart } from '../components/charts/EquityCurveChart';
import { PerformanceChart } from '../components/charts/PerformanceChart';
import { SetupFunnelChart } from '../components/charts/SetupFunnelChart';
import { NumberInput } from '../components/forms/NumberInput';
import { SelectInput } from '../components/forms/SelectInput';
import { DataTable } from '../components/tables/DataTable';
import { TextInput } from '../components/forms/TextInput';
import type { BacktestRun, CsvUpload } from '../types/backtesting';
import type { BotSettings } from '../types/settings';
import { BACKTESTING_PROFILE_OPTIONS, DEFAULT_PRODUCTION_PROFILE, PROFILE_FREEZE_WARNING, TIMEFRAME_PROFILES } from '../utils/constants';

export function Backtesting({ runs, settings, onRefresh }: { runs: BacktestRun[]; settings: BotSettings | null; onRefresh: () => Promise<void> }) {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [manualSymbol, setManualSymbol] = useState('');
  const [timeframeProfile, setTimeframeProfile] = useState(settings?.default_timeframe_profile ?? TIMEFRAME_PROFILES[0]);
  const [startingBalance, setStartingBalance] = useState(settings?.starting_balance ?? '');
  const [risk, setRisk] = useState(settings?.risk_amount_per_trade ?? '');
  const [maxLeverage, setMaxLeverage] = useState(settings?.max_leverage ?? '');
  const [fees, setFees] = useState('0');
  const [slippage, setSlippage] = useState('0');
  const [profile, setProfile] = useState(settings?.default_backtesting_profile ?? DEFAULT_PRODUCTION_PROFILE);
  const [researchExpansionMin, setResearchExpansionMin] = useState('1.0');
  const [researchExpansionMax, setResearchExpansionMax] = useState('4.0');
  const [researchRetraceWindow, setResearchRetraceWindow] = useState('3');
  const [researchTpModel, setResearchTpModel] = useState('RR_1_0_RESEARCH');
  const [timeExitMinutes, setTimeExitMinutes] = useState(settings?.time_exit_minutes ?? '30');
  const [researchRequireExpansionC3, setResearchRequireExpansionC3] = useState('true');
  const [researchUseLinkedFvgDetection, setResearchUseLinkedFvgDetection] = useState('true');
  const [researchMainFvgMatchMode, setResearchMainFvgMatchMode] = useState('C2_IMMEDIATE');
  const [researchMainFvgMatchWindow, setResearchMainFvgMatchWindow] = useState('0');
  const [timeExitMinutesTouched, setTimeExitMinutesTouched] = useState(false);
  const [profileTouched, setProfileTouched] = useState(false);
  const [status, setStatus] = useState('Idle');
  const [statusTone, setStatusTone] = useState<'idle' | 'busy' | 'ok' | 'error'>('idle');
  const [isUploading, setIsUploading] = useState(false);
  const [lastUploadFile, setLastUploadFile] = useState<File | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [uploadedCsv, setUploadedCsv] = useState<CsvUpload | null>(null);
  const [selectedRun, setSelectedRun] = useState<BacktestRun | null>(null);
  const researchMode = profile === 'PROFILE_G_CODEX_OPTIMIZED' || profile === 'PROFILE_RECOVERED_HIGH_WINRATE' || profile === 'PROFILE_2';
  const recoveredMode = profile === 'PROFILE_RECOVERED_HIGH_WINRATE';
  const profile2Mode = profile === 'PROFILE_2';
  const activeRun = selectedRun ?? runs[0];
  const activeSummary = activeRun?.report?.summary as Record<string, unknown> | undefined;

  useEffect(() => {
    if (!profileTouched && settings?.default_backtesting_profile) {
      setProfile(settings.default_backtesting_profile);
    }
    if (settings?.default_timeframe_profile) {
      setTimeframeProfile(settings.default_timeframe_profile);
    }
    if (settings?.risk_amount_per_trade) {
      setRisk(settings.risk_amount_per_trade);
    }
    if (settings?.max_leverage) {
      setMaxLeverage(settings.max_leverage);
    }
    if (settings?.starting_balance) {
      setStartingBalance(settings.starting_balance);
    }
    if (!timeExitMinutesTouched && settings?.time_exit_minutes) {
      setTimeExitMinutes(settings.time_exit_minutes);
    }
  }, [profileTouched, settings, timeExitMinutesTouched]);

  useEffect(() => {
    if (profile === 'PROFILE_RECOVERED_HIGH_WINRATE' || profile === 'PROFILE_2') {
      setResearchExpansionMin('1.0');
      setResearchExpansionMax('3.0');
      setResearchRetraceWindow('3');
      setResearchTpModel('LEG_TARGET_RESEARCH');
      setResearchRequireExpansionC3('false');
      setResearchUseLinkedFvgDetection('false');
      setResearchMainFvgMatchMode('LEGACY_EXPANSION_OR_NEXT_CANDLE');
      setResearchMainFvgMatchWindow('1');
      setTimeframeProfile('PROFILE_15_10_5');
    } else if (profile === 'PROFILE_G_CODEX_OPTIMIZED') {
      setResearchExpansionMin('1.0');
      setResearchExpansionMax('4.0');
      setResearchRetraceWindow('3');
      setResearchTpModel('RR_1_0_RESEARCH');
      setResearchRequireExpansionC3('true');
      setResearchUseLinkedFvgDetection('true');
      setResearchMainFvgMatchMode('C2_IMMEDIATE');
      setResearchMainFvgMatchWindow('0');
    }
  }, [profile]);

  const selectedSymbol = (manualSymbol || symbol).trim().toUpperCase();
  const symbolOptions = Array.from(new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', uploadedCsv?.detected_symbol, selectedSymbol].filter(Boolean) as string[]));

  async function handleUpload(file: File) {
    setLastUploadFile(file);
    setIsUploading(true);
    setStatusTone('busy');
    try {
      setStatus(`Uploading ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)}MB) - large files can take a while to parse`);
      setUploadId(null);
      setUploadedCsv(null);
      const uploaded = await uploadCsv(file, selectedSymbol);
      setUploadId(uploaded.upload_id);
      setUploadedCsv(uploaded);
      if (uploaded.detected_symbol && uploaded.detected_symbol !== 'UNKNOWN') {
        setSymbol(uploaded.detected_symbol);
        setManualSymbol('');
      }
      setStatus(`CSV uploaded: ${uploaded.filename} (${uploaded.candles_loaded} candles)`);
      setStatusTone('ok');
    } catch (error) {
      setUploadId(null);
      setUploadedCsv(null);
      setStatus(error instanceof Error ? `CSV upload failed: ${error.message}` : 'CSV upload failed');
      setStatusTone('error');
    } finally {
      setIsUploading(false);
    }
  }

  async function handleRun() {
    setStatusTone('busy');
    try {
      setStatus(`Running ${profile}`);
      if (!uploadId) {
        setStatus('Backtest failed: upload a CSV first');
        setStatusTone('error');
        return;
      }
      if (!uploadedCsv || uploadedCsv.upload_id !== uploadId) {
        setStatus('Backtest failed: upload metadata is stale. Upload the CSV again.');
        setStatusTone('error');
        return;
      }
      if (!selectedSymbol) {
        setStatus('Backtest failed: select or enter a symbol');
        setStatusTone('error');
        return;
      }
      const run = await runBacktest({
        upload_id: uploadId,
        symbol: selectedSymbol,
        profile_id: profile,
        selected_strategy_profile: profile,
        timeframe_profile: timeframeProfile,
        starting_balance: startingBalance,
        fixed_risk_amount: risk,
        risk_per_trade: risk,
        max_leverage: maxLeverage,
        selected_max_leverage: maxLeverage,
        selected_trade_mode: 'BACKTEST',
        selected_exchange: 'BACKTEST',
        fees,
        slippage,
        selected_tp_model: researchMode ? researchTpModel : settings?.selected_rr_profile ?? 'RR_1_5',
        selected_rr_profile: researchMode ? researchTpModel : settings?.selected_rr_profile ?? 'RR_1_5',
        time_exit_minutes: (researchMode ? researchTpModel : settings?.selected_rr_profile) === 'TIME_BASED_EXIT' ? timeExitMinutes : undefined,
        selected_time_exit_minutes: (researchMode ? researchTpModel : settings?.selected_rr_profile) === 'TIME_BASED_EXIT' ? timeExitMinutes : undefined,
        research_mode: researchMode,
        ...(researchMode ? {
          research_expansion_min: researchExpansionMin,
          research_expansion_max: researchExpansionMax,
          research_retrace_window_8m_candles: researchRetraceWindow,
          research_tp_model: researchTpModel,
          research_require_expansion_c3: researchRequireExpansionC3,
          research_use_linked_fvg_detection: researchUseLinkedFvgDetection,
          research_main_fvg_match_mode: researchMainFvgMatchMode,
          research_main_fvg_match_window_candles: researchMainFvgMatchWindow,
        } : {}),
      });
      setSelectedRun(run);
      await onRefresh();
      setStatus(`${profile} backtest complete`);
      setStatusTone('ok');
    } catch (error) {
      setStatus(error instanceof Error ? `Backtest failed: ${error.message}` : 'Backtest failed');
      setStatusTone('error');
    }
  }

  async function openRun(run: BacktestRun) {
    setStatusTone('busy');
    try {
      setStatus(`Loading details for ${run.run_id}`);
      setSelectedRun(await getBacktestRun(run.run_id));
      setStatus(`Viewing details for ${run.run_id}`);
      setStatusTone('ok');
    } catch (error) {
      setSelectedRun(run);
      setStatus(error instanceof Error ? `Could not load ${run.run_id}: ${error.message}` : `Could not load ${run.run_id}`);
      setStatusTone('error');
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Backtesting</h1>
      <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">{PROFILE_FREEZE_WARNING}</div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-6">
        <SelectInput label="Symbol" value={symbol} options={symbolOptions} onChange={(value) => { setSymbol(value); setManualSymbol(''); }} />
        <TextInput label="Manual Symbol Override" value={manualSymbol} onChange={(value) => setManualSymbol(value.toUpperCase())} placeholder="Optional, e.g. ETHUSDT" />
        <SelectInput label="Backtesting Strategy Profile" value={profile} options={[...BACKTESTING_PROFILE_OPTIONS]} onChange={(value) => { setProfileTouched(true); setProfile(value); }} />
        <SelectInput label="Timeframe Profile" value={timeframeProfile} options={[...TIMEFRAME_PROFILES]} onChange={setTimeframeProfile} />
        <NumberInput label="Starting Balance" value={startingBalance} onChange={setStartingBalance} />
        <NumberInput label="Fixed Risk Amount" value={risk} onChange={setRisk} />
        <NumberInput label="Max Leverage" value={maxLeverage} onChange={setMaxLeverage} />
        <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100">
          {researchMode ? `Research TP model: ${researchTpModel}` : `Selected TP model: ${settings?.selected_rr_profile ?? 'RR_1_5'}`}
        </div>
        {(researchMode ? researchTpModel : settings?.selected_rr_profile) === 'TIME_BASED_EXIT' && (
          <>
            <NumberInput label="Time Exit Minutes" value={timeExitMinutes} onChange={(value) => { setTimeExitMinutesTouched(true); setTimeExitMinutes(value); }} />
            <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100">
              Trade will close after this many minutes from entry, whether in profit or loss.
            </div>
          </>
        )}
        <NumberInput label="Fees" value={fees} onChange={setFees} />
        <NumberInput label="Slippage" value={slippage} onChange={setSlippage} />
        <div className={`rounded-md border px-3 py-2 text-xs ${researchMode ? 'border-amber-400/40 bg-amber-400/10 text-amber-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>
          {researchMode ? 'Research-only profile active' : 'Production-safe profile active'}
        </div>
        <input className="md:col-span-2" type="file" accept=".csv" disabled={isUploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void handleUpload(file); }} />
        <button
          className="rounded-md border border-slate-700 px-3 py-2 text-sm font-semibold text-slate-200 disabled:opacity-40"
          disabled={!lastUploadFile || isUploading}
          onClick={() => lastUploadFile && void handleUpload(lastUploadFile)}
        >
          {isUploading ? 'Uploading…' : 'Retry Upload'}
        </button>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 md:col-span-2" onClick={() => void handleRun()}>Run Backtest</button>
      </div>
      {researchMode && (
        <div className="grid gap-3 rounded-lg border border-amber-400/30 bg-amber-400/10 p-4 md:grid-cols-8">
          <NumberInput label={profile2Mode ? 'Profile 2 Expansion Min' : recoveredMode ? 'Recovered Expansion Min' : 'Profile G Expansion Min'} value={researchExpansionMin} onChange={setResearchExpansionMin} />
          <NumberInput label={profile2Mode ? 'Profile 2 Expansion Max' : recoveredMode ? 'Recovered Expansion Max' : 'Profile G Expansion Max'} value={researchExpansionMax} onChange={setResearchExpansionMax} />
          <NumberInput label={profile2Mode ? 'Profile 2 Retrace Window' : recoveredMode ? 'Recovered Retrace Window' : 'Profile G Retrace Window'} value={researchRetraceWindow} onChange={setResearchRetraceWindow} />
          <SelectInput label={profile2Mode ? 'Profile 2 TP Model' : recoveredMode ? 'Recovered TP Model' : 'Profile G TP Model'} value={researchTpModel} options={['LEG_TARGET_RESEARCH', 'RR_1_0_RESEARCH', 'RR_1_5', 'TIME_BASED_EXIT']} onChange={setResearchTpModel} />
          <SelectInput label="Require C3 Expansion" value={researchRequireExpansionC3} options={['true', 'false']} onChange={setResearchRequireExpansionC3} />
          <SelectInput label="Linked FVG Detection" value={researchUseLinkedFvgDetection} options={['true', 'false']} onChange={setResearchUseLinkedFvgDetection} />
          <SelectInput label="Main FVG Match Mode" value={researchMainFvgMatchMode} options={['C2_IMMEDIATE', 'LEGACY_EXPANSION_OR_NEXT_CANDLE']} onChange={setResearchMainFvgMatchMode} />
          <NumberInput label="Main FVG Match Window" value={researchMainFvgMatchWindow} onChange={setResearchMainFvgMatchWindow} />
        </div>
      )}
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-2">
        <KeyValuePanel title="Uploaded CSV" rows={{
          filename: uploadedCsv?.filename ?? 'None selected',
          upload_id: uploadedCsv?.upload_id ?? 'None',
          candles_loaded: uploadedCsv?.candles_loaded ?? 'None',
          detected_symbol: uploadedCsv?.detected_symbol ?? 'None',
          start_time: uploadedCsv?.start_time ?? 'None',
          end_time: uploadedCsv?.end_time ?? 'None',
          candle_hash: shortHash(uploadedCsv?.candle_hash),
        }} />
        <KeyValuePanel title="Request Preview" rows={{
          upload_id: uploadId ?? 'None',
          filename: uploadedCsv?.filename ?? 'None',
          symbol: selectedSymbol || 'None',
          profile_id: profile,
          timeframe_profile: timeframeProfile,
          research_mode: researchMode ? 'YES' : 'NO',
          research_expansion_min: researchMode ? researchExpansionMin : 'N/A',
          research_expansion_max: researchMode ? researchExpansionMax : 'N/A',
          research_retrace_window_8m_candles: researchMode ? researchRetraceWindow : 'N/A',
          research_require_expansion_c3: researchMode ? researchRequireExpansionC3 : 'N/A',
          research_use_linked_fvg_detection: researchMode ? researchUseLinkedFvgDetection : 'N/A',
          research_main_fvg_match_mode: researchMode ? researchMainFvgMatchMode : 'N/A',
          research_main_fvg_match_window_candles: researchMode ? researchMainFvgMatchWindow : 'N/A',
          candles_loaded: uploadedCsv?.candles_loaded ?? 'None',
          starting_balance: startingBalance,
          fixed_risk_amount: risk,
          selected_max_leverage: maxLeverage,
          margin_mode: 'isolated',
          selected_trade_mode: 'BACKTEST',
          selected_exchange: 'BACKTEST',
          tp_model: researchMode ? researchTpModel : settings?.selected_rr_profile ?? 'RR_1_5',
          time_exit_minutes: (researchMode ? researchTpModel : settings?.selected_rr_profile) === 'TIME_BASED_EXIT' ? timeExitMinutes : 'N/A',
          fees,
          slippage,
        }} />
      </div>
      <div
        className={`flex items-center gap-2 rounded-lg border p-4 text-sm ${
          statusTone === 'error'
            ? 'border-danger/40 bg-danger/10 text-danger'
            : statusTone === 'ok'
              ? 'border-success/40 bg-success/10 text-success'
              : statusTone === 'busy'
                ? 'border-action/40 bg-action/10 text-action'
                : 'border-slate-800 bg-panel text-slate-200'
        }`}
      >
        {isUploading && <span className="h-4 w-4 flex-none animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />}
        <span>Backtest status: {status}</span>
      </div>
      {activeRun && <BacktestRunDetails run={activeRun} />}
      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Total trades" value={(activeSummary?.performance_summary as Record<string, unknown> | undefined)?.total_trades ?? activeSummary?.trades_simulated ?? activeRun?.trades?.length ?? 0} />
        <Metric label="Wins" value={(activeSummary?.performance_summary as Record<string, unknown> | undefined)?.wins ?? activeSummary?.wins ?? 0} />
        <Metric label="Losses" value={(activeSummary?.performance_summary as Record<string, unknown> | undefined)?.losses ?? activeSummary?.losses ?? 0} />
        <Metric label="Invalidation blockers" value={activeSummary?.pipeline_blocked_stage ?? 'None'} />
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <EquityCurveChart data={activeRun?.equity_curve ?? []} />
        <SetupFunnelChart />
        <PerformanceChart />
      </div>
      <DataTable rows={runs} emptyLabel="No backtest runs" onRowClick={(run) => void openRun(run)} columns={[
        { header: 'Run', render: (row) => <span className="font-semibold text-action">{row.run_id}</span> },
        { header: 'File', render: (row) => row.filename ?? '-' },
        { header: 'Symbol', render: (row) => row.symbol },
        { header: 'Profile', render: (row) => row.profile_id ?? DEFAULT_PRODUCTION_PROFILE },
        { header: 'Timeframes', render: (row) => row.timeframe_profile ?? row.timeframe },
        { header: 'Candles', render: (row) => row.candles_loaded ?? '-' },
        { header: 'Hash', render: (row) => shortHash(row.candle_hash) },
        { header: 'Status', render: (row) => row.status },
      ]} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-4"><div className="text-xs text-muted">{label}</div><div className="text-xl text-ink">{String(value)}</div></div>;
}

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : 'None';
}

function KeyValuePanel({ title, rows }: { title: string; rows: Record<string, unknown> }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
      <div className="mb-2 text-xs uppercase text-muted">{title}</div>
      <div className="grid gap-2 text-sm">
        {Object.entries(rows).map(([key, value]) => <div key={key} className="flex justify-between gap-3"><span className="text-muted">{key}</span><span className="break-words text-slate-100">{String(value)}</span></div>)}
      </div>
    </div>
  );
}

function BacktestRunDetails({ run }: { run: BacktestRun }) {
  const rawSummary = run.report?.summary ?? {};
  const summary = typeof rawSummary === 'object' && rawSummary !== null ? rawSummary as Record<string, unknown> : { summary: rawSummary };
  const funnel = (summary.strategy_funnel ?? {}) as Record<string, unknown>;
  const profileApplied = (summary.profile_applied ?? run.profile_applied ?? {}) as Record<string, unknown>;
  const profileLock = (summary.profile_lock_verification ?? run.profile_lock_verification ?? {}) as Record<string, unknown>;
  const performance = (summary.performance_summary ?? {}) as Record<string, unknown>;
  const trades = ((summary.trade_list ?? run.trades ?? []) as Record<string, unknown>[]);
  const invalidations = (summary.setups_invalidated_with_reason_counts ?? {}) as Record<string, unknown>;
  const warnings = (summary.warnings ?? run.warnings ?? []) as unknown[];
  const summaryRows = Object.entries(summary).filter(([key]) => key !== 'strategy_funnel');
  return (
    <div className="space-y-3 rounded-lg border border-slate-800 bg-panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-ink">Backtest Details</h2>
        <div className="rounded-md border border-action/30 bg-action/10 px-3 py-1 text-xs text-action">Selected run: {run.run_id} - {run.profile_id ?? DEFAULT_PRODUCTION_PROFILE}</div>
      </div>
      {warnings.length > 0 && <div className="rounded-md border border-amber-400/40 bg-amber-400/10 p-3 text-sm text-amber-100">{warnings.map(String).join(' ')}</div>}
      {/* items-start: panels in the same row vary wildly in content length (Dataset has
          9 rows, Profile Applied ~28; Strategy Funnel has 50+, Invalidations can have 0) -
          without it, grid's default stretch makes a short/empty panel match its much
          taller row-mate's height, leaving large blocks of dead space. */}
      <div className="grid items-start gap-3 lg:grid-cols-2">
        <KeyValuePanel title="Dataset" rows={{
          upload_id: summary.upload_id ?? run.upload_id ?? 'None',
          filename: summary.filename ?? run.filename ?? 'None',
          symbol: summary.symbol ?? run.symbol,
          detected_symbol: summary.detected_symbol ?? run.detected_symbol ?? 'None',
          candles_loaded: summary.candles_loaded ?? run.candles_loaded ?? 'None',
          candle_hash: summary.candle_hash ?? run.candle_hash ?? 'None',
          data_start_time: summary.data_start_time ?? run.data_start_time ?? 'None',
          data_end_time: summary.data_end_time ?? run.data_end_time ?? 'None',
          strategy_source: summary.strategy_source ?? 'None',
        }} />
        <KeyValuePanel title="Profile Applied" rows={profileApplied} />
        <KeyValuePanel title="Profile Lock Verification" rows={{
          frontend_selected_profile: profileLock.frontend_selected_profile ?? summary.frontend_selected_profile ?? run.selected_profile_id ?? 'None',
          api_selected_profile: profileLock.api_selected_profile ?? summary.api_selected_profile ?? run.selected_strategy_profile ?? 'None',
          backend_resolved_profile: profileLock.backend_resolved_profile ?? summary.backend_resolved_profile ?? run.profile_id ?? 'None',
          strategy_applied_profile: profileLock.strategy_applied_profile ?? summary.strategy_applied_profile ?? summary.applied_profile_id ?? 'None',
          trades_checked: profileLock.trades_checked ?? trades.length,
          mismatched_trades_count: profileLock.mismatched_trades_count ?? 'None',
          profile_lock_status: profileLock.profile_lock_status ?? 'None',
          selected_profile_actively_used_by_backend: profileLock.selected_profile_actively_used_by_backend ?? 'NO',
        }} />
        <KeyValuePanel title="Performance Summary" rows={{
          total_trades: performance.total_trades ?? trades.length,
          closed_trades: performance.closed_trades ?? 0,
          wins: performance.wins ?? 0,
          losses: performance.losses ?? 0,
          open_or_unresolved: performance.open_or_unresolved_trades ?? 0,
          win_rate: performance.win_rate ?? 0,
          net_profit: performance.net_profit ?? 0,
          gross_profit: performance.gross_profit ?? 0,
          gross_loss: performance.gross_loss ?? 0,
          profit_factor: performance.profit_factor ?? 0,
          max_drawdown: performance.max_drawdown ?? 0,
          expectancy: performance.expectancy_per_trade ?? performance.expectancy ?? 'None',
          average_rr: performance.average_rr ?? summary.average_rr ?? 'None',
          average_time_to_hit_tp: performance.average_time_to_hit_tp_human ?? 'N/A',
          average_time_to_hit_tp_seconds: performance.average_time_to_hit_tp_seconds ?? 'N/A',
          average_time_to_hit_tp_minutes: performance.average_time_to_hit_tp_minutes ?? 'N/A',
          fastest_time_to_hit_tp: performance.fastest_time_to_hit_tp ?? 'N/A',
          slowest_time_to_hit_tp: performance.slowest_time_to_hit_tp ?? 'N/A',
          median_time_to_hit_tp: performance.median_time_to_hit_tp ?? 'N/A',
          final_balance: performance.final_balance ?? 'None',
          selected_rr_profile: performance.selected_rr_profile ?? summary.selected_rr_profile ?? 'None',
          selected_tp_model: performance.selected_tp_model ?? summary.selected_tp_model ?? 'None',
          applied_tp_model: performance.applied_tp_model ?? summary.applied_tp_model ?? 'None',
          time_exit_minutes: performance.time_exit_minutes ?? summary.time_exit_minutes ?? 'N/A',
          time_exit_closed_count: performance.time_exit_closed_count ?? 'N/A',
          protective_sl_closed_count: performance.protective_sl_closed_count ?? 'N/A',
          average_time_in_trade_minutes: performance.average_time_in_trade_minutes ?? 'N/A',
          average_pnl_for_time_exit_trades: performance.average_pnl_for_time_exit_trades ?? 'N/A',
          win_rate_for_time_exit_trades: performance.win_rate_for_time_exit_trades ?? 'N/A',
          selected_rr_value: performance.selected_rr_value ?? summary.selected_rr_value ?? 'None',
          fixed_risk_amount: performance.fixed_risk_amount ?? summary.fixed_risk_amount ?? 'None',
        }} />
        <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 text-xs uppercase text-muted">Strategy Funnel</div>
          <div className="grid gap-2 text-sm">
            {Object.entries(funnel).map(([key, value]) => <div key={key} className="flex justify-between gap-3"><span className="text-muted">{key}</span><span className="text-slate-100">{String(value)}</span></div>)}
          </div>
        </div>
        <KeyValuePanel title="Invalidations" rows={invalidations} />
        <div className="overflow-auto rounded-md border border-slate-800 bg-slate-950 p-3 lg:col-span-2">
          <div className="mb-2 text-xs uppercase text-muted">Trades</div>
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="text-left text-xs uppercase text-muted">
              <tr>{['Trade ID', 'Selected Profile', 'Applied Profile', 'Timeframe Profile', 'Direction', 'Fixed Risk', 'Margin', 'Mode', 'Leverage', 'Expected SL Loss', 'RR Profile', 'Selected TP Model', 'Applied TP Model', 'TP Lock', 'Time Exit', 'Minutes', 'Planned Time Exit', 'Actual Exit', 'Entry Model', 'Entry time', 'Entry', 'SL', 'TP', 'Time Exit Price', 'Exit reason', 'Duration', 'Exit', 'Size', 'Risk', 'Expected Reward', 'Outcome', 'Net PnL', 'Actual RR'].map((header) => <th key={header} className="px-2 py-2 font-medium">{header}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {trades.length ? trades.map((trade, index) => (
                <tr key={String(trade.trade_id ?? index)}>
                  <td className="px-2 py-2 text-slate-200">{String(trade.trade_id ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.selected_profile_id ?? trade.selected_strategy_profile ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.applied_profile_id ?? trade.profile_id ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.timeframe_profile_id ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.direction ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.fixed_risk_amount ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.applied_margin_amount ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.margin_mode ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.applied_leverage ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.expected_loss_at_sl ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.selected_rr_profile ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.selected_tp_model ?? trade.selected_rr_profile ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.applied_tp_model ?? trade.tp_model ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.tp_model_lock_status ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.time_exit_enabled ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.time_exit_minutes ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.planned_time_exit_timestamp ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.actual_exit_timestamp ?? trade.exit_timestamp ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.entry_model ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.entry_timestamp ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.entry_price ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.stop_loss ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.take_profit ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.time_exit_price ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.exit_reason ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.duration_minutes ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.exit_timestamp ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.exit_price ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.position_size ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.actual_risk_amount ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.expected_reward_amount ?? '-')}</td>
                  <td className="px-2 py-2"><span className={`rounded border px-2 py-1 text-xs ${outcomeClass(String(trade.outcome ?? ''))}`}>{String(trade.outcome ?? '-')}</span></td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.net_pnl ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-200">{String(trade.actual_rr ?? trade.rr_realized ?? '-')}</td>
                </tr>
              )) : <tr><td className="px-2 py-3 text-muted" colSpan={33}>No trades found.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="max-h-[520px] overflow-auto rounded-md border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 text-xs uppercase text-muted">Run Summary</div>
          <div className="grid gap-2 text-sm">
            {summaryRows.map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(160px,1fr)_2fr] gap-3"><span className="text-muted">{key}</span><span className="break-words text-slate-100">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</span></div>)}
          </div>
        </div>
      </div>
    </div>
  );
}

function outcomeClass(outcome: string) {
  if (outcome === 'WIN') return 'border-emerald-400/40 bg-emerald-400/10 text-emerald-100';
  if (outcome === 'LOSS') return 'border-rose-400/40 bg-rose-400/10 text-rose-100';
  return 'border-amber-400/40 bg-amber-400/10 text-amber-100';
}
