export interface AgentDecision {
  agent_type: string
  direction: 'long' | 'short' | 'neutral'
  confidence: number
  price_target: number | null
  reasoning: string
  cot_reasoning: string | null
}

export interface BrooksAnalog {
  page_number: number
  pattern_type: string
  direction: string
  outcome: string
  probability: string
  always_in_direction: string
  day_type: string
  brooks_concepts: string[]
  similarity_score: number
  gcs_jpg_path: string
  analysis_summary: string
}

export interface ProbabilityDistribution {
  median: number
  mean: number
  std_dev: number
  percentile_5: number
  percentile_25: number
  percentile_75: number
  percentile_95: number
  skewness: number
  prob_up: number
  prob_down: number
  prob_flat: number
  scenario_probs: Record<string, number>
}

export interface CalibrationMetrics {
  is_calibrated: boolean
  calibration_sample_size: number
  expected_coverage: number
  observed_coverage: number | null
  interval_width_adjustment: number
  aci_alpha_current: number
  ece: number | null
}

export interface ForecastResult {
  forecast_id: string
  instrument: string
  forecast_horizon_minutes: number
  current_price: number
  forecast_text: string
  distribution: ProbabilityDistribution
  total_simulations: number
  successful_simulations: number
  sim_preset: string
  institutional_reasoning: string
  retail_reasoning: string
  market_maker_reasoning: string
  created_at: string
  pipeline_duration_seconds: number
  build_method: string
  calibration?: CalibrationMetrics
  agent_cot?: Record<string, string>
  agent_analogs?: Record<string, BrooksAnalog[]>
}

export type SimPreset = 'simple' | 'quick' | 'standard' | 'deep'

export interface FastPathResult {
  forecast_id: string
  instrument: string
  forecast_horizon_minutes: number
  current_price: number
  prob_up: number
  prob_down: number
  prob_flat: number
  predicted_direction: string
  direction_confidence: number
  predicted_p5: number
  predicted_p95: number
  predicted_median: number
  forecast_text: string
  feature_count: number
  model_trained_at: string | null
  model_sample_size: number
  inference_ms: number
  pipeline_duration_seconds: number
  created_at: string
  build_method: 'fast_path'
}

export interface SimPresetConfig {
  label: string
  sims: number
  time: string
  cost: string
}

export const SIM_PRESETS: Record<SimPreset, SimPresetConfig> = {
  simple: { label: 'Simple', sims: 0, time: '~5s', cost: '$0' },
  quick: { label: 'Quick', sims: 100, time: '~90s', cost: '~$1.50' },
  standard: { label: 'Standard', sims: 200, time: '~2.5min', cost: '~$3' },
  deep: { label: 'Deep', sims: 500, time: '~6min', cost: '~$7' },
}
