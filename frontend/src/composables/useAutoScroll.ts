import { ref, nextTick, watch, type Ref } from 'vue'

export function useAutoScroll(containerRef: Ref<HTMLElement | null>, dependency: Ref<unknown>) {
  const userScrolledUp = ref(false)

  function onScroll() {
    if (!containerRef.value) return
    const el = containerRef.value
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
    userScrolledUp.value = !atBottom
  }

  async function scrollToBottom() {
    if (userScrolledUp.value) return
    await nextTick()
    if (containerRef.value) {
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }

  watch(dependency, scrollToBottom, { deep: true })

  return { userScrolledUp, onScroll, scrollToBottom }
}
