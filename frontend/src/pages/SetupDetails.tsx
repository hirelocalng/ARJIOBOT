import { SetupStateTimeline } from '../components/radar/SetupStateTimeline';
import type { RadarSetup } from '../types/radar';

export function SetupDetails({ setup }: { setup: RadarSetup }) {
  return (
    <div className="mt-5 space-y-4">
      <h2 className="text-lg font-semibold text-ink">Setup Details</h2>
      <div className="grid gap-3 rounded-lg border border-slate-800 bg-panel p-4 md:grid-cols-4">
        {Object.entries(setup).map(([key, value]) => (
          <div key={key}>
            <div className="text-xs text-muted">{key}</div>
            <div className="break-words text-sm text-ink">{Array.isArray(value) ? value.join(', ') : value && typeof value === 'object' ? JSON.stringify(value) : value ?? '—'}</div>
          </div>
        ))}
      </div>
      <SetupStateTimeline />
    </div>
  );
}
