import { ref, type Ref } from 'vue'

/**
 * Composable that fetches and caches a signed URL for a Brooks chart JPG.
 * Cached for 50 minutes (signed URLs last 60 minutes).
 */
const urlCache = new Map<number, { url: string; fetchedAt: number }>()
const CACHE_TTL_MS = 50 * 60 * 1000

export function useBrooksChart() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function getSignedUrl(pageId: number): Promise<string | null> {
    // Check cache
    const cached = urlCache.get(pageId)
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      return cached.url
    }

    loading.value = true
    error.value = null

    try {
      const resp = await fetch(`/api/brooks/chart/${pageId}`)
      if (!resp.ok) {
        const data = await resp.json()
        throw new Error(data.error || `HTTP ${resp.status}`)
      }
      const data = await resp.json()
      const url = data.signed_url as string

      // Cache the result
      urlCache.set(pageId, { url, fetchedAt: Date.now() })
      return url
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to load chart'
      return null
    } finally {
      loading.value = false
    }
  }

  return { getSignedUrl, loading, error }
}
