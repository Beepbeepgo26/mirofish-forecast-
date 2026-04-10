export interface AgentDecision {
  agent_type: string
  direction: 'long' | 'short' | 'neutral'
  confidence: number
  price_target: number | null
  reasoning: string
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
}

export type SimPreset = 'quick' | 'standard' | 'deep'

export interface SimPresetConfig {
  label: string
  sims: number
  time: string
  cost: string
}

export const SIM_PRESETS: Record<SimPreset, SimPresetConfig> = {
  quick: { label: 'Quick', sims: 100, time: '~90s', cost: '~$1.50' },
  standard: { label: 'Standard', sims: 200, time: '~2.5min', cost: '~$3' },
  deep: { label: 'Deep', sims: 500, time: '~6min', cost: '~$7' },
}
