<script setup lang="ts">
import { computed } from 'vue'
import type { Itinerary } from '../api'

const props = defineProps<{ itinerary: Itinerary; selected: number; previewCounts?: number[] }>()
const emit = defineEmits<{ select: [index: number] }>()
// Summarize saved API facts only. Scheduling and route calculation stay on the server.
const days = computed(() => props.itinerary.days.map(day => ({
  date: day.date,
  stops: day.stops.length,
  stay: day.stops.reduce((sum, stop) => sum + stop.stay_minutes, 0),
  travel: day.stops.reduce((sum, stop) => sum + (stop.travel_to_next?.duration_min ?? 0), 0),
  distance: day.stops.reduce((sum, stop) => sum + (stop.travel_to_next?.distance_km ?? 0), 0),
  cost: day.stops.reduce((sum, stop) => sum + (stop.user_cost ?? 0), 0),
  missingCost: day.stops.filter(stop => stop.user_cost == null).length,
})))
function navigate(event: KeyboardEvent, index: number) {
  const last = days.value.length - 1
  const next = event.key === 'ArrowRight' ? (index + 1) % (last + 1)
    : event.key === 'ArrowLeft' ? (index + last) % (last + 1)
    : event.key === 'Home' ? 0 : event.key === 'End' ? last : undefined
  if (next === undefined) return
  event.preventDefault()
  emit('select', next)
  const group = (event.currentTarget as HTMLElement).parentElement
  group?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus()
}
</script>

<template>
  <div class="day-overview">
    <div class="overview-heading"><strong>多日概览</strong><small>{{previewCounts ? '编辑地点预览 · 交通与时间保存后重算' : '站间交通来自已保存路线 · 费用由用户录入'}}</small></div>
    <div class="overview-grid" role="group" aria-label="行程日期">
      <button v-for="(day, index) in days" :key="index" type="button" class="overview-day" :class="{selected: selected === index}" :aria-pressed="selected === index" @click="emit('select', index)" @keydown="navigate($event, index)">
        <span class="day-label"><strong>DAY {{index + 1}}</strong><span>{{selected === index ? '当前查看' : '查看当天'}}</span></span>
        <span class="overview-date">{{previewCounts ? '原日期 ' : ''}}{{day.date}}</span>
        <template v-if="previewCounts">
          <span class="overview-stations">{{previewCounts[index] ?? 0}} 站 · 编辑预览</span>
          <span class="overview-muted">路线、时间与费用待保存核算</span>
        </template>
        <template v-else>
          <span class="overview-stations">{{day.stops}} 站 · 停留 {{day.stay}} 分钟</span>
          <span>站间交通 {{day.travel}} 分钟 · {{day.distance.toFixed(2)}} km</span>
          <span class="overview-cost">已录入站点费用 ¥{{day.cost.toFixed(2)}}</span>
          <span class="overview-muted">{{day.missingCost ? `${day.missingCost} 站费用未填` : '站点费用已填齐'}} · 不含未录入费用</span>
        </template>
      </button>
    </div>
  </div>
</template>

<style scoped>
.day-overview{padding:0 24px 20px}.overview-heading{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 16px;margin-bottom:12px}.overview-heading strong{font-size:14px}.overview-heading small{color:#66736d;font-size:11px}.overview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:10px}.overview-day{display:flex;flex-direction:column;gap:6px;text-align:left;border:1px solid #dce4dd;border-radius:12px;background:#fafbf8;padding:14px;color:#33443b;font:inherit;font-size:12px;cursor:pointer;min-width:0}.overview-day:hover{border-color:#8ca78f;background:#f4f8f1}.overview-day.selected{border-color:#365d42;background:#edf4e9;box-shadow:inset 0 0 0 1px #365d42}.overview-day:focus-visible{outline:3px solid #3768ab;outline-offset:3px}.day-label{display:flex;justify-content:space-between;gap:8px;align-items:center;color:#32523c}.day-label strong{font-size:13px;letter-spacing:1px}.day-label>span{font-size:10px}.overview-date{color:#65766b;font-size:11px;margin-bottom:4px}.overview-stations{font-weight:600}.overview-cost{margin-top:4px}.overview-muted{font-size:11px;color:#66736d;line-height:1.6}@media(max-width:680px){.day-overview{padding:0 16px 16px}.overview-grid{grid-template-columns:1fr}.overview-day{padding:12px}}
</style>
