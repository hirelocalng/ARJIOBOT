type Props = { label: string; value: string | number; detail?: string };

export function MetricCard({ label, value, detail }: Props) {
  return (
    // flex/justify-between + h-full: cards in the same grid row already stretch to
    // match the tallest one (grid default), so this pins each card's detail line to
    // the bottom consistently - otherwise a long value (e.g. a profile id) wraps to
    // two lines and pushes that one card's detail line lower than its row-mates'.
    <div className="flex h-full flex-col justify-between gap-2 rounded-lg border border-slate-800 bg-panel p-4">
      <div>
        <div className="text-xs text-muted">{label}</div>
        {/* break-words: long values (e.g. PROFILE_RECOVERED_HIGH_WINRATE) wrap inside
            the card instead of overflowing past its border into the next card. */}
        <div className="mt-2 break-words text-2xl font-semibold text-ink">{value}</div>
      </div>
      {detail && <div className="text-xs text-slate-400">{detail}</div>}
    </div>
  );
}
