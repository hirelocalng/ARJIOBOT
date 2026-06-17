export const LIVE_TRADING_DISABLED_MESSAGE = 'Live trading disabled. Paper mode only.';

export function confirmDangerousAction(message: string): boolean {
  return window.confirm(message);
}

export function assertMaskedCredential(value: string): boolean {
  return value.includes('****') && !value.toLowerCase().includes('secret');
}
