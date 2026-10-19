<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import type { Itinerary, Poi } from '../api'

const props = defineProps<{ itinerary: Itinerary | null; selectedDay: number; poi?: Poi | null }>()
const container = ref<HTMLDivElement>()
const error = ref('')
const ready = ref(false)
const configured = Boolean(import.meta.env.VITE_AMAP_JS_KEY)
// JS SDK is dynamically loaded only after the user configures its browser key.
let map: any, sdk: any, disposed = false
const stops = computed(() => props.itinerary?.days[props.selectedDay]?.stops || [])
function redraw() {
  if (!map || !sdk) return
  map.clearMap()
  const overlays: any[] = []
  for (const [index, stop] of stops.value.entries()) {
    const marker = new sdk.Marker({ position: [stop.poi.longitude, stop.poi.latitude], title: `${index + 1}. ${stop.poi.name}`, label: { content: String(index + 1), direction: 'top' } })
    overlays.push(marker)
    if (stop.travel_to_next?.polyline.length) {
      overlays.push(new sdk.Polyline({ path: stop.travel_to_next.polyline.map(p => [p.longitude, p.latitude]), strokeColor: '#238776', strokeWeight: 5, strokeOpacity: 0.85, showDir: true }))
    }
  }
  if (props.poi) overlays.push(new sdk.Marker({position: [props.poi.longitude, props.poi.latitude], title: props.poi.name}))
  if (overlays.length) { map.add(overlays); map.setFitView(overlays, false, [70,70,70,70]) }
}
onMounted(async () => {
  if (!configured) return
  try {
    if (import.meta.env.VITE_AMAP_SECURITY_CODE) {
      (window as any)._AMapSecurityConfig = { securityJsCode: import.meta.env.VITE_AMAP_SECURITY_CODE }
    }
    sdk = await AMapLoader.load({ key: import.meta.env.VITE_AMAP_JS_KEY, version: '2.0' })
    if (disposed) return
    map = new sdk.Map(container.value, { zoom: 5, viewMode: '2D' })
    ready.value = true
    redraw()
  } catch { error.value = '地图加载失败，请检查浏览器地图 Key、域名授权和网络。' }
})
watch(() => [props.itinerary, props.selectedDay, props.poi], redraw, { deep: true })
onBeforeUnmount(() => { disposed = true; map?.destroy() })
</script>

<template>
  <section class="map-panel">
    <div ref="container" class="map-canvas" aria-label="高德地图" />
    <div v-if="!ready" class="map-empty">
      <span class="map-symbol">⌖</span><h3>{{ error ? '地图暂不可用' : configured ? '地图加载中' : '连接真实地图' }}</h3>
      <p>{{ error || (configured ? '正在加载高德地图' : '配置浏览器地图 Key 后，将显示地点与真实道路路线。') }}</p>
      <small v-if="!configured">当前可使用表单、任务状态、时间轴与 POI 列表。</small>
    </div>
    <div class="map-caption"><span class="dot"/>高德地图 · GCJ-02<span>路线来自授权接口</span></div>
  </section>
</template>
