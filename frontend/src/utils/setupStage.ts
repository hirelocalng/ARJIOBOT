// Maps the Setup Radar spec's current_stage/last_valid_stage values (see
// _display_current_stage in radar.py) to friendly labels. Direction matters
// for the swing stage: a BEARISH setup is built on a 16M swing high, a
// BULLISH one on a swing low.
export function friendlyStageLabel(currentStage: string, direction?: string): string {
  const isBullish = direction === 'BULLISH';
  switch (currentStage) {
    case '16M_SWING_DETECTED':
      return isBullish ? '16M swing low detected' : '16M swing high detected';
    case '16M_EXPANSION_DETECTED':
      return '16M expansion detected';
    case '16M_FVG_DETECTED':
      return '16M FVG detected';
    case '12M_FVG_DETECTED':
      return '12M FVG detected';
    case '8M_FVG_DETECTED':
      return '8M FVG detected';
    case 'WAITING_RETRACE':
      return 'waiting for retrace';
    case 'ENTRY_READY':
      return 'entry-ready / 100%';
    case 'INVALIDATED':
      return 'invalidated';
    case 'EXPIRED':
      return 'expired';
    default:
      return currentStage;
  }
}
