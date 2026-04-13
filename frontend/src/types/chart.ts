export interface OHLCVBar {
  time: number // Unix timestamp
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface OHLCVResponse {
  instrument: string
  interval: string
  count: number
  bars: OHLCVBar[]
}

export interface ForecastOverlay {
  forecastId: string
  startTime: number // Unix timestamp when forecast was made
  endTime: number // Unix timestamp when horizon expires
  currentPrice: number
  median: number
  p5: number
  p25: number
  p75: number
  p95: number
  calP5?: number
  calP95?: number
}
