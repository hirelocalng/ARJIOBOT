export const NAV_ITEMS = [
  'Trading Control Center',
  'Dashboard',
  'Setup Radar',
  'Markets/Pairs',
  'Accounts',
  'Account Status',
  'Strategy',
  'Risk',
  'Signals',
  'Trade Plans',
  'Executions',
  'Backtesting',
  'Reports',
  'Settings'
] as const;

export type PageName = (typeof NAV_ITEMS)[number];

export const TIMEFRAME_PROFILES = [
  'DEFAULT_16_12_8',
  'PROFILE_15_10_5',
  'PROFILE_30_16_8',
  'PROFILE_12_8_4',
  'PROFILE_8_4_2',
];

export const BACKTESTING_PROFILES = [
  'STRICT_PROFILE',
  'PROFILE_F_VOLUME',
  'PROFILE_F_BALANCED',
  'PROFILE_F_SELECTIVE',
  'PROFILE_G_CODEX_OPTIMIZED',
  'PROFILE_RECOVERED_HIGH_WINRATE',
  'PROFILE_2',
] as const;

export const QUARANTINED_BACKTESTING_PROFILES = [
  'STRICT_PROFILE',
  'PROFILE_F_VOLUME',
  'PROFILE_F_BALANCED',
  'PROFILE_F_SELECTIVE',
  'PROFILE_G_CODEX_OPTIMIZED',
] as const;

export const DEFAULT_PRODUCTION_PROFILE = 'PROFILE_RECOVERED_HIGH_WINRATE' as const;

export const BACKTESTING_PROFILE_OPTIONS = [
  { value: 'PROFILE_RECOVERED_HIGH_WINRATE', label: 'Recovered High Winrate (Research)' },
  { value: 'PROFILE_2', label: 'Profile 2' },
] as const;

export const PROFILE_FREEZE_WARNING = 'Strategy profile is frozen. Trade connection and risk settings can be changed, but profile logic cannot be edited.' as const;

export const TP_MODEL_OPTIONS = [
  'RR_1_0',
  'RR_1_0_RESEARCH',
  'RR_1_5',
  'LEG_TARGET_RESEARCH',
  'TIME_BASED_EXIT',
] as const;

export const PRODUCTION_RR_PROFILE = 'RR_1_5' as const;
export const PRODUCTION_RR_VALUE = '1.5' as const;
