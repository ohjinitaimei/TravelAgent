<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import type { Itinerary, Poi } from '../api'

const props = defineProps<{ itinerary: Itinerary | null; selectedDay: number; poi?: Poi | null; selectedPoiId?:string|null; preview?:Poi[]; anchors?:{origin:Poi|null;destination:Poi|null} }>()
const emit=defineEmits<{select:[id:string]}>()
const container = ref<HTMLDivElement>()
const error = ref('')
const ready = ref(false)
const configured = Boolean(import.meta.env.VITE_AMAP_JS_KEY)
// JS SDK is dynamically loaded only after the user configures its browser key.
let map: any, sdk: any, disposed = false
const stops = computed(() => props.preview?.map(poi=>({poi,travel_to_next:null}))??props.itinerary?.days[props.selectedDay]?.stops??[])
const boundary=computed(()=>props.anchors??{origin:props.itinerary?.days[props.selectedDay]?.origin_poi,destination:props.itinerary?.days[props.selectedDay]?.destination_poi})
const markers=new Map<string,{marker:any;button:HTMLButtonElement;poi:Poi}>()
const lines:{line:any;origin:string;destination:string}[]=[]
function highlight(pan=false) {
  for(const [id,value] of markers){const active=id===props.selectedPoiId;value.button.classList.toggle('active',active);value.button.setAttribute('aria-pressed',String(active));value.marker.setzIndex(active?200:100)}
  for(const item of lines){const active=item.origin===props.selectedPoiId||item.destination===props.selectedPoiId;item.line.setOptions({strokeColor:active?'#b77d28':'#238776',strokeWeight:active?7:5})}
  const selected=props.selectedPoiId?markers.get(props.selectedPoiId):null
  if(pan&&selected)map?.panTo([selected.poi.longitude,selected.poi.latitude])
}
function redraw() {
  if (!sdk || disposed) return
  // Reset SDK rendering state when day, overlays or editing layout changes.
  // Reusing the prior view can leave WebKit's base layer blank after resizing.
  map?.destroy()
  map = new sdk.Map(container.value, { zoom: 5, viewMode: '2D' })
  markers.clear();lines.length=0
  const overlays: any[] = []
  for (const [index, stop] of stops.value.entries()) {
    const button=document.createElement('button')
    button.type='button';button.className='map-stop-marker';button.textContent=String(index+1)
    button.setAttribute('aria-label',`地图标记 ${index+1} ${stop.poi.name}`)
    button.addEventListener('click',event=>{event.stopPropagation();emit('select',stop.poi.id)})
    const marker = new sdk.Marker({ position: [stop.poi.longitude, stop.poi.latitude], title: `${index + 1}. ${stop.poi.name}`, content:button,anchor:'bottom-center' })
    markers.set(stop.poi.id,{marker,button,poi:stop.poi})
    overlays.push(marker)
    if (stop.travel_to_next?.polyline.length) {
      const line=new sdk.Polyline({ path: stop.travel_to_next.polyline.map(p => [p.longitude, p.latitude]), strokeColor: '#238776', strokeWeight: 5, strokeOpacity: 0.85, showDir: true })
      overlays.push(line);lines.push({line,origin:stop.travel_to_next.origin_id,destination:stop.travel_to_next.destination_id})
    }
  }
  for(const [label,poi] of [['出发地',boundary.value.origin],['返回地',boundary.value.destination]] as const) {
    if(!poi||markers.has(poi.id))continue
    const button=document.createElement('button')
    button.type='button';button.className='map-stop-marker';button.textContent=boundary.value.origin?.id===boundary.value.destination?.id?'出/返':label==='出发地'?'出':'返'
    button.setAttribute('aria-label',`地图${label} ${poi.name}`)
    button.addEventListener('click',()=>emit('select',poi.id))
    const marker=new sdk.Marker({position:[poi.longitude,poi.latitude],title:`${label} ${poi.name}`,content:button,anchor:'bottom-center'})
    markers.set(poi.id,{marker,button,poi});overlays.push(marker)
  }
  if(!props.preview)for(const leg of [props.itinerary?.days[props.selectedDay]?.origin_segment,props.itinerary?.days[props.selectedDay]?.destination_segment]) {
    if(!leg?.polyline.length)continue
    const line=new sdk.Polyline({path:leg.polyline.map(p=>[p.longitude,p.latitude]),strokeColor:'#238776',strokeWeight:5,strokeOpacity:.85,showDir:true})
    overlays.push(line);lines.push({line,origin:leg.origin_id,destination:leg.destination_id})
  }
  if (props.poi&&!markers.has(props.poi.id)) overlays.push(new sdk.Marker({position: [props.poi.longitude, props.poi.latitude], title: props.poi.name}))
  if (overlays.length) { map.add(overlays); map.setFitView(overlays, false, [70,70,70,70]) }
  highlight()
}
onMounted(async () => {
  if (!configured) return
  try {
    (window as any)._AMapSecurityConfig = { serviceHost: `${window.location.origin}/api/v1/travel/_AMapService` }
    sdk = await AMapLoader.load({ key: import.meta.env.VITE_AMAP_JS_KEY, version: '2.0' })
    if (disposed) return
    ready.value = true
    redraw()
  } catch { error.value = '地图加载失败，请检查浏览器地图 Key、域名授权和网络。' }
})
watch(() => [props.itinerary, props.selectedDay, props.poi,props.preview,props.anchors], redraw, { deep: true, flush:'post' })
watch(()=>props.selectedPoiId,()=>highlight(true))
onBeforeUnmount(() => { disposed = true; map?.destroy();markers.clear();lines.length=0 })
</script>

<template>
  <section class="map-panel">
    <div ref="container" class="map-canvas" aria-label="高德地图" />
    <div v-if="!ready" class="map-empty">
      <span class="map-symbol">⌖</span><h3>{{ error ? '地图暂不可用' : configured ? '地图加载中' : '连接真实地图' }}</h3>
      <p>{{ error || (configured ? '正在加载高德地图' : '配置浏览器地图 Key 后，将显示地点与真实道路路线。') }}</p>
      <small v-if="!configured">当前可使用表单、任务状态、时间轴与 POI 列表。</small>
    </div>
    <details v-if="stops.length" class="map-stop-list"><summary>地图地点（{{stops.length}}）</summary><button v-for="(stop,i) in stops" :key="stop.poi.id" :aria-label="`地图列表 ${i+1} ${stop.poi.name}`" :aria-pressed="selectedPoiId===stop.poi.id" @click="emit('select',stop.poi.id)">{{i+1}}. {{stop.poi.name}}</button><div v-if="boundary.origin||boundary.destination" role="group" aria-label="地图起终点"><button v-if="boundary.origin" :aria-pressed="selectedPoiId===boundary.origin.id" @click="emit('select',boundary.origin.id)">地图出发地 {{boundary.origin.name}}</button><button v-if="boundary.destination" :aria-pressed="selectedPoiId===boundary.destination.id" @click="emit('select',boundary.destination.id)">地图返回地 {{boundary.destination.name}}</button></div></details>
    <div class="map-caption"><span class="dot"/>{{preview?'编辑地点预览':'高德地图 · GCJ-02'}}<span>{{preview?'路线保存后重算':'路线来自授权接口'}}</span></div>
  </section>
</template>

<style scoped>
:global(.map-stop-marker){width:34px;height:34px;border:2px solid #245c50;border-radius:50% 50% 50% 4px;background:white;color:#245c50;font-weight:700;box-shadow:0 2px 7px #18392c40;padding:0;cursor:pointer}
:global(.map-stop-marker.active){background:#245c50;color:white;box-shadow:0 0 0 5px #e3aa5077}
.map-stop-list{position:absolute;top:14px;left:14px;z-index:2;max-width:calc(100% - 28px);padding:10px 12px;background:#fffffff5;border:1px solid var(--line);border-radius:8px;font-size:11px;box-shadow:0 2px 10px #18392c10}.map-stop-list summary{cursor:pointer;color:var(--green)}.map-stop-list button{display:block;text-align:left;padding:9px 5px;max-width:250px;overflow-wrap:anywhere;border:0;background:none;color:var(--green)}.map-stop-list button[aria-pressed=true]{font-weight:700;background:#eaf3e9;border-radius:5px}
</style>
