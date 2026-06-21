// Maps the internal SetupState enum (current_state) to the friendly stage
// names from the Setup Radar spec. Direction matters for the swing stage:
// a BEARISH setup is built on a 16M swing high, a BULLISH one on a swing low.
export function friendlyStageLabel(currentState: string, direction?: string): string {
  const isBullish = direction === 'BULLISH';
  switch (currentState) {
    case 'SWING_16M_CONFIRMED':
      return isBullish ? '16M swing low detected' : '16M swing high detected';
    case 'EXPANSION_16M_CONFIRMED':
      return '16M expansion detected';
    case 'FVG_16M_CONFIRMED':
      return '16M FVG detected';
    case 'FVG_12M_CONFIRMED':
      return '12M FVG detected';
    case 'FVG_8M_CONFIRMED':
      return '8M FVG detected';
    case 'WAITING_FOR_12M_RETRACE':
    case 'ONE_MINUTE_CONFIRMATION_ACTIVE':
    case 'ONE_MINUTE_SWING_CONFIRMED':
    case 'ONE_MINUTE_FVG_CONFIRMED':
      return 'waiting for retrace';
    case 'ENTRY_READY':
    case 'COMPLETED':
      return 'entry-ready / 100%';
    case 'INVALIDATED':
      return 'invalidated';
    case 'EXPIRED':
      return 'expired';
    default:
      return currentState;
  }
}
