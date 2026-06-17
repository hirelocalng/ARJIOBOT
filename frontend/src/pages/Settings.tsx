import { useEffect, useState } from 'react';
import { getBitgetCredentialStatus, getBitgetMode, switchBitgetMode, testLiveConnection, type TradingMode } from '../api/bitget';
import { selectActiveAccount } from '../api/accounts';
import { toggleLiveTrading } from '../api/liveTrading';
import { updateSettings } from '../api/settings';
import { SelectInput } from '../components/forms/SelectInput';
import { TextInput } from '../components/forms/TextInput';
import { Toggle } from '../components/forms/Toggle';
import type { ControlPlaneSnapshot } from '../types/controlPlane';
import type { BotSettings } from '../types/settings';
import type { ExchangeAccount } from '../types/accounts';
import { BACKTESTING_PROFILE_OPTIONS, DEFAULT_PRODUCTION_PROFILE, PROFILE_FREEZE_WARNING, TIMEFRAME_PROFILES, TP_MODEL_OPTIONS } from '../utils/constants';

export function Settings({ settings, onRefresh, controlPlane, accounts }: { settings: BotSettings | null; onRefresh: () => Promise<void>; controlPlane: ControlPlaneSnapshot | null; accounts: ExchangeAccount[] }) {
  const [profile, setProfile] = useState(settings?.default_timeframe_profile ?? TIMEFRAME_PROFILES[0]);
  const [backtestingProfile, setBacktestingProfile] = useState(settings?.default_backtesting_profile ?? DEFAULT_PRODUCTION_PROFILE);
  const [apiBaseUrl, setApiBaseUrl] = useState(settings?.api_base_url ?? import.meta.env.VITE_API_BASE_URL ?? '');
  const [refreshInterval, setRefreshInterval] = useState(settings?.refresh_interval_seconds ?? '15');
  const [paperModeDisplay, setPaperModeDisplay] = useState(settings?.paper_mode_display ?? true);
  const [startingBalance, setStartingBalance] = useState(settings?.starting_balance ?? '');
  const [riskAmount, setRiskAmount] = useState(settings?.risk_amount_per_trade ?? '');
  const [maxLeverage, setMaxLeverage] = useState(settings?.max_leverage ?? '');
  const [maxDailyLoss, setMaxDailyLoss] = useState(settings?.max_daily_loss ?? '');
  const [maxWeeklyLoss, setMaxWeeklyLoss] = useState(settings?.max_weekly_loss ?? '');
  const [tpModel, setTpModel] = useState(settings?.selected_rr_profile ?? 'RR_1_5');
  const [timeExitMinutes, setTimeExitMinutes] = useState(settings?.time_exit_minutes ?? '30');
  const [timeExitMinutesTouched, setTimeExitMinutesTouched] = useState(false);
  const [adapterMode, setAdapterMode] = useState(settings?.adapter_mode ?? 'MOCK');
  const [tradingMode, setTradingMode] = useState<TradingMode>((settings?.trading_mode as TradingMode | undefined) ?? 'OFF');
  const [liveConfirmation, setLiveConfirmation] = useState('');
  const [understandRealFunds, setUnderstandRealFunds] = useState(false);
  const [activeAccountId, setActiveAccountId] = useState(settings?.active_account_id ?? '');
  const [bitgetStatus, setBitgetStatus] = useState<Record<string, unknown> | null>(null);
  const [saveStatus, setSaveStatus] = useState('No changes saved yet');
  const resolveSelectedAccountId = (candidate: string) => resolveAccountId(candidate, accounts, controlPlane);

  useEffect(() => {
    if (settings) {
      setProfile(settings.default_timeframe_profile ?? TIMEFRAME_PROFILES[0]);
      setBacktestingProfile(settings.default_backtesting_profile ?? DEFAULT_PRODUCTION_PROFILE);
      setApiBaseUrl(settings.api_base_url ?? import.meta.env.VITE_API_BASE_URL ?? '');
      setRefreshInterval(settings.refresh_interval_seconds ?? '15');
      setPaperModeDisplay(settings.paper_mode_display ?? true);
      setStartingBalance(settings.starting_balance ?? '');
      setRiskAmount(settings.risk_amount_per_trade ?? '');
      setMaxLeverage(settings.max_leverage ?? '');
      setMaxDailyLoss(settings.max_daily_loss ?? '');
      setMaxWeeklyLoss(settings.max_weekly_loss ?? '');
      setTpModel(settings.selected_rr_profile ?? 'RR_1_5');
      if (!timeExitMinutesTouched) {
        setTimeExitMinutes(settings.time_exit_minutes ?? '30');
      }
      setAdapterMode(settings.adapter_mode ?? 'MOCK');
      setTradingMode((settings.trading_mode as TradingMode | undefined) ?? 'OFF');
      setActiveAccountId(resolveSelectedAccountId(settings.active_account_id ?? ''));
    }
  }, [settings, accounts, controlPlane, timeExitMinutesTouched]);

  useEffect(() => {
    void refreshBitgetStatus();
  }, []);

  async function save() {
    try {
      setSaveStatus('Saving changes...');
      const saved = await updateSettings({
        default_timeframe_profile: profile,
        default_backtesting_profile: backtestingProfile,
        active_strategy_profile: backtestingProfile,
        refresh_interval_seconds: refreshInterval,
        paper_mode_display: paperModeDisplay,
        api_base_url: apiBaseUrl,
        starting_balance: startingBalance,
        risk_amount_per_trade: riskAmount,
        max_leverage: maxLeverage,
        max_daily_loss: maxDailyLoss,
        max_weekly_loss: maxWeeklyLoss,
        selected_rr_profile: tpModel,
        time_exit_minutes: timeExitMinutes,
        adapter_mode: adapterMode,
        trading_mode: tradingMode,
        active_account_id: selectedAccountId,
      });
      setTimeExitMinutes(saved.time_exit_minutes ?? timeExitMinutes);
      await onRefresh();
      setTimeExitMinutesTouched(false);
      setSaveStatus('Settings saved successfully');
    } catch (error) {
      setSaveStatus(error instanceof Error ? `Save failed: ${error.message}` : 'Save failed');
    }
  }

  async function refreshBitgetStatus() {
    try {
      const mode = await getBitgetMode();
      const credentials = await getBitgetCredentialStatus();
      setBitgetStatus({ ...mode, credentials });
    } catch (error) {
      setBitgetStatus({ error: error instanceof Error ? error.message : 'Could not load Bitget status' });
    }
  }

  async function applyTradingMode() {
    try {
      setSaveStatus(`Switching Bitget mode to ${tradingMode}...`);
      await switchBitgetMode(tradingMode, liveConfirmation);
      await updateSettings({ trading_mode: tradingMode, live_trading_enabled: tradingMode === 'LIVE' });
      await refreshBitgetStatus();
      await onRefresh();
      setSaveStatus(`Active execution mode: ${tradingMode}`);
    } catch (error) {
      setSaveStatus(error instanceof Error ? `Mode switch failed: ${error.message}` : 'Mode switch failed');
    }
  }

  async function setLiveTrading(enabled: boolean) {
    try {
      setSaveStatus(enabled ? 'Turning LIVE trading ON...' : 'Turning LIVE trading OFF...');
      const result = await toggleLiveTrading(enabled, understandRealFunds, liveConfirmation);
      await onRefresh();
      const message = String(result.message ?? (enabled ? 'LIVE TRADING ON' : 'LIVE TRADING OFF'));
      setSaveStatus(message);
      window.alert(message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Live trading toggle failed';
      setSaveStatus(message);
      window.alert(message);
    }
  }

  async function testConnection() {
    try {
      setSaveStatus('Testing LIVE Bitget connection...');
      await testLiveConnection();
      await refreshBitgetStatus();
      setSaveStatus('LIVE connection check passed');
    } catch (error) {
      setSaveStatus(error instanceof Error ? `Connection test failed: ${error.message}` : 'Connection test failed');
    }
  }

  async function applyActiveAccount() {
    try {
      if (!selectedAccountId) {
        setSaveStatus('No saved account selected');
        return;
      }
      setSaveStatus('Applying active Bitget account...');
      await selectActiveAccount(selectedAccountId);
      setActiveAccountId(selectedAccountId);
      await refreshBitgetStatus();
      await onRefresh();
      setSaveStatus('Active Bitget account applied');
    } catch (error) {
      setSaveStatus(error instanceof Error ? `Active account apply failed: ${error.message}` : 'Active account apply failed');
    }
  }

  const accountOptions = accounts.length
    ? accounts.map((account) => ({
        value: account.account_id,
        label: `${account.account_name} - ${account.connection_status ?? account.verification_status} - ${account.api_key}`,
      }))
    : [{ value: '', label: 'NO SAVED ACCOUNTS' }];
  const selectedAccountId = resolveSelectedAccountId(activeAccountId);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-ink">Settings</h1>
      <div className="grid gap-3 md:grid-cols-4">
        <StatusCard label="Active Profile" value={String(controlPlane?.active_strategy.selected_profile ?? settings?.active_strategy_profile ?? 'None')} />
        <StatusCard label="Active Mode" value={String(controlPlane?.active_exchange_mode.selected_trade_mode ?? settings?.trading_mode ?? 'OFF')} />
        <StatusCard label="Account" value={String(controlPlane?.active_account.connection_status ?? 'NOT CONNECTED')} />
        <StatusCard label="Applied State" value={saveStatus.includes('success') ? 'SAVED / APPLIED' : saveStatus === 'No changes saved yet' ? 'SAVED' : saveStatus} />
      </div>
      <div className="rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">{PROFILE_FREEZE_WARNING}</div>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-3">
        <SelectInput label="Timeframe Profile" value={profile} options={[...TIMEFRAME_PROFILES]} onChange={setProfile} />
        <SelectInput label="Production Strategy Profile" value={backtestingProfile} options={[...BACKTESTING_PROFILE_OPTIONS]} onChange={setBacktestingProfile} />
        <SelectInput label="TP Model" value={tpModel} options={[...TP_MODEL_OPTIONS]} onChange={setTpModel} />
        {tpModel === 'TIME_BASED_EXIT' && (
          <>
            <TextInput label="Time Exit Minutes" value={timeExitMinutes} onChange={(value) => { setTimeExitMinutesTouched(true); setTimeExitMinutes(value); }} />
            <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100">
              Trade will close after this many minutes from entry, whether in profit or loss.
            </div>
          </>
        )}
        <StatusCard label="Selected TP Model" value={tpModel} />
        <StatusCard label="Saved TP Model" value={String(settings?.selected_rr_profile ?? 'None')} />
        <StatusCard label="Applied TP Model" value={String(controlPlane?.active_strategy.applied_tp_model ?? 'None')} />
        <StatusCard label="Time Exit Minutes Selected" value={tpModel === 'TIME_BASED_EXIT' ? timeExitMinutes : 'N/A'} />
        <StatusCard label="Time Exit Minutes Saved" value={String(settings?.time_exit_minutes ?? 'None')} />
        <StatusCard label="Time Exit Minutes Applied" value={String(controlPlane?.active_strategy.time_exit_minutes_applied ?? 'N/A')} />
        <StatusCard label="Override Allowed" value={String(controlPlane?.active_strategy.tp_model_override_allowed ?? 'NO')} />
        <StatusCard label="TP Lock Status" value={String(controlPlane?.active_strategy.tp_model_lock_status ?? 'LOCKED')} />
        <TextInput label="API Base URL" value={apiBaseUrl} onChange={setApiBaseUrl} />
        <TextInput label="Refresh Interval Seconds" value={refreshInterval} onChange={setRefreshInterval} />
        <TextInput label="Starting Balance" value={startingBalance} onChange={setStartingBalance} />
        <TextInput label="Fixed Risk Amount" value={riskAmount} onChange={setRiskAmount} />
        <TextInput label="Max Leverage" value={maxLeverage} onChange={setMaxLeverage} />
        <TextInput label="Max Daily Loss" value={maxDailyLoss} onChange={setMaxDailyLoss} />
        <TextInput label="Max Weekly Loss" value={maxWeeklyLoss} onChange={setMaxWeeklyLoss} />
        <div className="rounded-md border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
          Live trading remains blocked backend-side unless credentials, pair, risk, RR, timeframe, and mode validation all pass.
        </div>
        <SelectInput label="Trading Mode" value={tradingMode} options={['OFF', 'DRY_RUN_PREVIEW', 'LIVE']} onChange={(value) => setTradingMode(value as TradingMode)} />
        <div className={`rounded-md border px-3 py-2 text-xs ${tradingMode === 'LIVE' ? 'border-red-400/50 bg-red-500/10 text-red-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>
          Active execution mode: {tradingMode}. Environment lock verified: {String(bitgetStatus?.environment_lock_verified ?? settings?.environment_lock_verified ?? 'NO')}
        </div>
        <StatusCard label="REST Base URL" value={String(controlPlane?.active_exchange_mode.rest_base_url ?? 'auto-managed')} />
        <StatusCard label="Credential Type" value={String(controlPlane?.active_exchange_mode.credential_type_used ?? 'LIVE')} />
        <StatusCard label="Connection Status" value={String(controlPlane?.active_account.connection_status ?? 'NOT CONNECTED')} />
        <StatusCard label="Last Account Check" value={String(controlPlane?.active_account.last_successful_api_ping_time ?? 'None')} />
        <StatusCard label="Last Market Price Fetch" value={String(controlPlane?.connection_diagnostics.last_market_price_fetch ?? controlPlane?.system_health.last_successful_market_poll ?? 'N/A')} />
        <TextInput label="LIVE Confirmation" value={liveConfirmation} onChange={setLiveConfirmation} placeholder="ENABLE LIVE" />
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" onClick={() => void applyTradingMode()}>Apply Trading Mode</button>
        <Toggle label="I understand this uses real funds" checked={understandRealFunds} onChange={setUnderstandRealFunds} />
        <button className="rounded-md bg-red-500 px-3 py-2 text-sm font-semibold text-white" onClick={() => void setLiveTrading(true)}>LIVE TRADING: ON</button>
        <button className="rounded-md bg-slate-700 px-3 py-2 text-sm font-semibold text-slate-100" onClick={() => void setLiveTrading(false)}>LIVE TRADING: OFF</button>
        <Toggle label="Paper Mode Status" checked={paperModeDisplay} onChange={setPaperModeDisplay} />
        <SelectInput label="Adapter Mode" value={adapterMode} options={['MOCK', 'BITGET_LIVE']} onChange={setAdapterMode} />
        <div className={`rounded-md border px-3 py-2 text-xs ${adapterMode === 'MOCK' ? 'border-amber-400/40 bg-amber-400/10 text-amber-100' : 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100'}`}>
          {adapterMode === 'MOCK' ? 'MOCK MODE ACTIVE - NOT REAL EXCHANGE DATA' : 'BITGET_LIVE selected - monitoring will use real Bitget public data'}
        </div>
        <SelectInput label="Active Bitget Account" value={selectedAccountId} options={accountOptions} onChange={setActiveAccountId} />
        <StatusCard label="Current Active Account" value={String(controlPlane?.active_account.account_name ?? 'NONE')} />
        <StatusCard label="Active Account Status" value={String(controlPlane?.active_account.connection_status ?? 'NOT CONNECTED')} />
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950" disabled={!accounts.length} onClick={() => void applyActiveAccount()}>{accounts.length ? 'Apply Active Account' : 'Go to Accounts Page to Connect Account'}</button>
        <div className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-muted md:col-span-2">
          API credentials are managed only on the Accounts page. Settings only selects the saved account used for monitoring, readiness, and live execution.
        </div>
        <button className="rounded-md bg-slate-800 px-3 py-2 text-sm font-semibold text-slate-100" onClick={() => void testConnection()}>Test LIVE Connection</button>
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-muted md:col-span-3">
          Bitget status: {JSON.stringify(bitgetStatus ?? {})}
        </div>
        <div className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-muted md:col-span-3">
          Settings is configuration-only. Current active, saved, and applied values are verified from the Trading Control Center snapshot.
        </div>
        <div className="rounded-md border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-100 md:col-span-3">{saveStatus}</div>
        <button className="rounded-md bg-action px-3 py-2 text-sm font-semibold text-slate-950 md:col-span-3" onClick={() => void save()}>Save Settings</button>
      </div>
    </div>
  );
}

function resolveAccountId(candidate: string, accounts: ExchangeAccount[], controlPlane: ControlPlaneSnapshot | null): string {
  if (candidate && accounts.some((account) => account.account_id === candidate)) return candidate;
  const controlAccountId = String(controlPlane?.active_account.account_id ?? '');
  if (controlAccountId && accounts.some((account) => account.account_id === controlAccountId)) return controlAccountId;
  return accounts.find((account) => account.is_default || account.is_active)?.account_id ?? accounts[0]?.account_id ?? '';
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-800 bg-panel p-4"><div className="text-xs text-muted">{label}</div><div className="text-lg text-ink">{value}</div></div>;
}
