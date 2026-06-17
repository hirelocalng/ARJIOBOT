const STATES = ['HTF FVG', '16M Swing', '16M Expansion', '16M FVG', '12M FVG', '8M FVG', 'Retracement', '1M Confirmation', 'Entry Ready'];

export function SetupStateTimeline() {
  return (
    <ol className="grid gap-2 md:grid-cols-3">
      {STATES.map((state, index) => (
        <li key={state} className="rounded-md border border-slate-800 bg-panel p-3 text-sm">
          <div className="text-xs text-muted">Step {index + 1}</div>
          <div className="text-ink">{state}</div>
        </li>
      ))}
    </ol>
  );
}
