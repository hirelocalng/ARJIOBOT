import type { RadarSetup } from './radar';

export type SetupDetail = RadarSetup & {
  htf_fvg_id?: string;
  swing_16m_id?: string;
  expansion_16m_id?: string;
  fvg_16m_id?: string;
  fvg_12m_id?: string;
  fvg_8m_id?: string;
  one_minute_swing_id?: string;
  entry_fvg_id?: string;
  target_a_price?: string;
  target_b_price?: string;
  final_target_price?: string;
};

export type SetupHistoryItem = { state: string; changed_at: string };
