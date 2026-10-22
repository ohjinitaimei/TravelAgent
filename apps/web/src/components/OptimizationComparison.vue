<script setup lang="ts">
import type { Schema } from '../api'
defineProps<{ summary: Schema<'GroupingOptimization'> }>()
const reasons = {
  improved: '已采用地理分组，减少交通或每日负担。',
  feasible_candidate: '原分日不满足时段或交通上限，已采用满足所设约束的分组。',
  baseline_preferred: '候选分组未同时改善交通与每日负担，保留原分日。',
  tool_budget_limited: '为每日往返预留查询额度后，未比较额外分日候选，保留原分日。',
  no_geographic_change: '当前地理分组未找到改进候选，保留原分日。',
}
</script>

<template>
  <section class="optimization-comparison" aria-label="分日与交通对比">
    <div class="comparison-title"><strong>分日与交通对比</strong><span>{{ summary.applied ? '已调整分日' : '保留原分日' }}</span></div>
    <p>{{ reasons[summary.reason] }}</p>
    <table>
      <caption>本次真实路线查询结果</caption>
      <thead><tr><th scope="col">指标</th><th scope="col">原分日</th><th scope="col">本次采用</th></tr></thead>
      <tbody>
        <tr><th scope="row">已选交通距离</th><td>{{ summary.baseline.distance_km.toFixed(2) }} km</td><td>{{ summary.result.distance_km.toFixed(2) }} km</td></tr>
        <tr><th scope="row">已选交通时间</th><td>{{ summary.baseline.travel_minutes }} 分钟</td><td>{{ summary.result.travel_minutes }} 分钟</td></tr>
        <tr><th scope="row">最忙一天总时长</th><td>{{ summary.baseline.busiest_day_minutes }} 分钟</td><td>{{ summary.result.busiest_day_minutes }} 分钟</td></tr>
      </tbody>
    </table>
    <small>对应当前保存版本；总时长含停留、站间交通及所选起终点往返。{{ summary.baseline.feasible ? '' : '原分日不满足每日时段或所设交通上限。' }}{{ summary.candidate_search_limited ? `候选站间路线查询上限 ${summary.candidate_route_limit} 次，已预留每日往返额度。` : '' }}仅比较有限候选，不保证全局最优或未来路况。</small>
  </section>
</template>

<style scoped>
.optimization-comparison{padding:18px 24px;background:#f5f8f3;border-bottom:1px solid var(--line);font-size:12px}
.comparison-title{display:flex;gap:12px;align-items:center;justify-content:space-between}.comparison-title span{color:var(--green);font-size:11px}
p{margin:10px 0;color:var(--muted);line-height:1.7}table{width:100%;border-collapse:collapse;text-align:left;font-size:11px}caption{text-align:left;color:var(--muted);padding:0 0 8px}
th,td{padding:8px 6px;border-top:1px solid var(--line);font-weight:400}thead th{font-weight:600}td:last-child{color:var(--green);font-weight:600}small{display:block;line-height:1.8;color:var(--muted);margin-top:10px}
@media(max-width:680px){.optimization-comparison{padding:16px}}
</style>
