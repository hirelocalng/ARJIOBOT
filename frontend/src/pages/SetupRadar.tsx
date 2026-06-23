import { useState } from 'react';
import { SetupRadarTable } from '../components/radar/SetupRadarTable';
import { SetupCompletedTable } from '../components/radar/SetupCompletedTable';
import { SetupHistoryTable } from '../components/radar/SetupHistoryTable';
import { clearSetupHistory } from '../api/admin';
import { confirmDangerousAction } from '../utils/safety';
import type { RadarSetup } from '../types/radar';

type Tab = 'IN_PROGRESS' | 'COMPLETED' | 'INVALIDATED';

// completed/invalidated are each capped at the latest 100 in their own store
// (see _evict_oldest in live_setup_detection.py), but completed.length can
// still exceed 100 since the COMPLETED endpoint also includes uncapped
// pending-ENTRY_READY setups not yet moved into the capped store - cap the
// displayed count itself so the subtitle never implies more history is kept
// than actually is.
function cappedCountLabel(count: number, label: string): string {
  return count > 100 ? `100 ${label} (latest 100)` : `${count} ${label}`;
}

export function SetupRadar({
  inProgress,
  completed,
  invalidated,
  onSelect
}: {
  inProgress: RadarSetup[];
  completed: RadarSetup[];
  invalidated: RadarSetup[];
  onSelect: (setup: RadarSetup) => void;
}) {
  const [activeTab, setActiveTab] = useState<Tab>('IN_PROGRESS');
  const [clearingHistory, setClearingHistory] = useState(false);

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'IN_PROGRESS', label: 'In Progress', count: inProgress.length },
    { id: 'COMPLETED', label: 'Completed', count: completed.length },
    { id: 'INVALIDATED', label: 'Invalidated', count: invalidated.length }
  ];

  const handleClearHistory = async () => {
    if (!confirmDangerousAction('Clear all completed/invalidated setup history? This cannot be undone.')) return;
    setClearingHistory(true);
    try {
      await clearSetupHistory();
      window.location.reload();
    } finally {
      setClearingHistory(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Setup Radar</h1>
          <p className="text-sm text-muted">
            {inProgress.length} in progress · {cappedCountLabel(completed.length, 'completed')} · {cappedCountLabel(invalidated.length, 'invalidated')}
          </p>
        </div>
        <button
          className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm font-semibold text-danger disabled:opacity-60"
          disabled={clearingHistory}
          onClick={() => void handleClearHistory()}
        >
          {clearingHistory ? 'Clearing...' : 'Clear History'}
        </button>
      </div>
      <div className="flex gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-md border px-4 py-2 text-sm font-semibold transition-colors ${
              activeTab === tab.id ? 'border-action bg-action/10 text-action' : 'border-slate-800 bg-panel text-muted hover:text-ink'
            }`}
          >
            {tab.label.toUpperCase()} ({tab.count})
          </button>
        ))}
      </div>
      {activeTab === 'IN_PROGRESS' && <SetupRadarTable setups={inProgress} onSelect={onSelect} />}
      {activeTab === 'COMPLETED' && <SetupCompletedTable setups={completed} onSelect={onSelect} />}
      {activeTab === 'INVALIDATED' && <SetupHistoryTable setups={invalidated} onSelect={onSelect} />}
    </div>
  );
}
