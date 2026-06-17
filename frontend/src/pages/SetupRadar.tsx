import { SetupRadarTable } from '../components/radar/SetupRadarTable';
import type { RadarSetup } from '../types/radar';

export function SetupRadar({ setups, onSelect }: { setups: RadarSetup[]; onSelect: (setup: RadarSetup) => void }) {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Setup Radar</h1>
        <p className="text-sm text-muted">Only real backend-tracked live or explicit backtest setup candidates are shown. No tracked candidate means no radar row.</p>
      </div>
      <SetupRadarTable setups={setups} onSelect={onSelect} />
    </div>
  );
}
