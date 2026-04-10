export const COLORS = {
  base: '#0a0a0f',
  panel: '#111118',
  surface: '#1a1a24',
  border: '#2e2e3e',
  textPrimary: '#e5e7eb',
  textSecondary: '#9ca3af',
  accent: '#2962FF',
  bullish: '#22c55e',
  bearish: '#ef4444',
  warning: '#f59e0b',
} as const

export const CHART_THEME = {
  backgroundColor: 'transparent',
  textStyle: { color: '#9ca3af', fontFamily: 'Inter' },
  splitLine: { lineStyle: { color: '#2e2e3e' } },
  axisLine: { lineStyle: { color: '#2e2e3e' } },
} as const
