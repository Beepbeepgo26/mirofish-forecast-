export interface SSEEvent {
  stage: string
  timestamp: string
  status?: 'started' | 'completed' | 'progress' | 'error'
  message?: string
  progress?: number
  completed?: number
  total?: number
  query?: Record<string, unknown>
  context_summary?: Record<string, unknown>
  scenarios_summary?: Array<{
    rank: string
    name: string
    probability: number
  }>
  forecast?: Record<string, unknown>
  error?: string
}
