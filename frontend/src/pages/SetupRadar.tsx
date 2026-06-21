import { useState } from 'react';
import { SetupRadarTable } from '../components/radar/SetupRadarTable';
import { SetupCompletedTable } from '../components/radar/SetupCompletedTable';
import { SetupHistoryTable } from '../components/radar/SetupHistoryTable';
import type { RadarSetup } from '../types/radar';

type Tab = 'IN_PROGRESS' | 'COMPLETED' | 'INVALIDATED';

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

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'IN_PROGRESS', label: 'In Progress', count: inProgress.length },
    { id: 'COMPLETED', label: 'Completed', count: completed.length },
    { id: 'INVALIDATED', label: 'Invalidated', count: invalidated.length }
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">Setup Radar</h1>
        <p className="text-sm text-muted">
          {inProgress.length} in progress · {completed.length} completed · {invalidated.length} invalidated (latest 100)
        </p>
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
