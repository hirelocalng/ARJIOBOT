import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Layout } from './components/layout/Layout';
import type { ExchangeAccount } from './types/accounts';
import type { BacktestRun } from './types/backtesting';
import type { BotStatus } from './types/common';
import type { ExecutionRecord } from './types/execution';
import type { MonitoredPair } from './types/pairs';
import type { RadarSetup } from './types/radar';
import type { TradePlan } from './types/risk';
import type { TradeSignal } from './types/signals';
import type { BotSettings } from './types/settings';
import type { ControlPlaneSnapshot } from './types/controlPlane';
import type { PageName } from './utils/constants';
import { getStatus } from './api/health';
import { listAccounts } from './api/accounts';
import { listPairs } from './api/pairs';
import { getSettings } from './api/settings';
import { getControlPlane } from './api/controlPlane';
import { getRadar, getRadarHistory } from './api/radar';
import { listSignals } from './api/signals';
import { listTradePlans } from './api/risk';
import { listExecutions } from './api/execution';
import { listBacktestRuns } from './api/backtesting';
import { getAuthStatus } from './api/auth';
import { getDashboardToken } from './api/client';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { MobileControl } from './pages/MobileControl';
import { PairManager } from './pages/PairManager';
import { AccountManager } from './pages/AccountManager';
import { AccountStatus } from './pages/AccountStatus';
import { RiskSettings } from './pages/RiskSettings';
import { SetupRadar } from './pages/SetupRadar';
import { SetupDetails } from './pages/SetupDetails';
import { Signals } from './pages/Signals';
import { TradePlans } from './pages/TradePlans';
import { Executions } from './pages/Executions';
import { Backtesting } from './pages/Backtesting';
import { Reports } from './pages/Reports';
import { Settings } from './pages/Settings';
import { TradingControlCenter } from './pages/TradingControlCenter';
import { Strategy } from './pages/Strategy';

export function App() {
  const [page, setPage] = useState<PageName>('Trading Control Center');
  const [authRequired, setAuthRequired] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [accounts, setAccounts] = useState<ExchangeAccount[]>([]);
  const [pairs, setPairs] = useState<MonitoredPair[]>([]);
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [setups, setSetups] = useState<RadarSetup[]>([]);
  const [setupHistory, setSetupHistory] = useState<RadarSetup[]>([]);
  const [signals, setSignals] = useState<TradeSignal[]>([]);
  const [plans, setPlans] = useState<TradePlan[]>([]);
  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [controlPlane, setControlPlane] = useState<ControlPlaneSnapshot | null>(null);
  const [selectedSetupId, setSelectedSetupId] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const refreshInFlight = useRef(false);

  async function refresh() {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const results = await Promise.allSettled([
        getStatus(),
        listAccounts(),
        listPairs(),
        getSettings(),
        getRadar(),
        getRadarHistory(),
        listSignals(),
        listTradePlans(),
        listExecutions(),
        listBacktestRuns(),
        getControlPlane()
      ]);
      const errors: string[] = [];
      const value = <T,>(index: number, fallback: T): T => {
        const result = results[index];
        if (result.status === 'fulfilled') return result.value as T;
        errors.push(result.reason instanceof Error ? result.reason.message : String(result.reason));
        return fallback;
      };
      setStatus(value(0, status));
      setAccounts(value(1, accounts));
      setPairs(value(2, pairs));
      setSettings(value(3, settings));
      setSetups(value(4, setups));
      setSetupHistory(value(5, setupHistory));
      setSignals(value(6, signals));
      setPlans(value(7, plans));
      setExecutions(value(8, executions));
      setRuns(value(9, runs));
      setControlPlane(value(10, controlPlane));
      setApiError(errors.length ? errors.join(' | ') : null);
    } finally {
      refreshInFlight.current = false;
    }
  }

  useEffect(() => {
    async function boot() {
      try {
        const auth = await getAuthStatus();
        setAuthRequired(auth.auth_required);
        const hasToken = Boolean(getDashboardToken());
        const isAuthenticated = !auth.auth_required || hasToken;
        setAuthenticated(isAuthenticated);
        setAuthReady(true);
        if (isAuthenticated) {
          void refresh();
        }
      } catch (error) {
        setApiError(error instanceof Error ? error.message : 'API route unavailable');
      } finally {
        setAuthReady(true);
      }
    }
    void boot();
  }, []);

  useEffect(() => {
    if (!authReady || !authenticated) return;
    const interval = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [authReady, authenticated]);

  const defaultAccount = accounts.find((account) => account.is_default || account.is_active);
  const selectedSetup = useMemo(() => setups.find((setup) => setup.setup_id === selectedSetupId) ?? setups[0], [setups, selectedSetupId]);

  const pages: Record<PageName, ReactNode> = {
    'Trading Control Center': <TradingControlCenter controlPlane={controlPlane} onRefresh={refresh} />,
    Dashboard: <Dashboard status={status} accounts={accounts} pairs={pairs} setups={setups} signals={signals} plans={plans} executions={executions} runs={runs} apiError={apiError} controlPlane={controlPlane} />,
    'Setup Radar': (
      <>
        <SetupRadar setups={setups} history={setupHistory} onSelect={(setup) => setSelectedSetupId(setup.setup_id)} />
        {selectedSetup && <SetupDetails setup={selectedSetup} />}
      </>
    ),
    'Markets/Pairs': <PairManager pairs={pairs} onRefresh={refresh} controlPlane={controlPlane} />,
    Accounts: <AccountManager accounts={accounts} onRefresh={refresh} controlPlane={controlPlane} />,
    'Account Status': <AccountStatus onRefresh={refresh} />,
    Strategy: <Strategy controlPlane={controlPlane} settings={settings} onRefresh={refresh} />,
    Risk: <RiskSettings settings={settings} onRefresh={refresh} controlPlane={controlPlane} />,
    Signals: <Signals signals={signals} setups={setups} onRefresh={refresh} />,
    'Trade Plans': <TradePlans plans={plans} signals={signals} onRefresh={refresh} />,
    Executions: <Executions executions={executions} plans={plans} onRefresh={refresh} />,
    Backtesting: <Backtesting runs={runs} settings={settings} onRefresh={refresh} />,
    Reports: <Reports />,
    Settings: <Settings settings={settings} onRefresh={refresh} controlPlane={controlPlane} accounts={accounts} />
  };

  if (!authReady) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">Loading dashboard...</div>;
  }

  if (authRequired && !authenticated) {
    return <Login onAuthenticated={() => { setAuthenticated(true); void refresh(); }} />;
  }

  return (
    <Layout active={page} status={status} defaultAccount={defaultAccount} onNavigate={setPage}>
      {pages[page]}
    </Layout>
  );
}
