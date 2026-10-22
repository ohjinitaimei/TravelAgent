<script setup lang="ts">
import { computed } from 'vue'
import type { Itinerary } from '../api'
import { planningChanges, planningRatings, longestSavedLeg } from '../planning'
const props=defineProps<{itinerary:Itinerary;disabled?:boolean}>()
const emit=defineEmits<{locate:[day:number,id:string];baseline:[]}>()
const summary=computed(()=>props.itinerary.planning_comparison)
const ratings=computed(()=>planningRatings(props.itinerary))
const changes=computed(()=>planningChanges(props.itinerary))
const longest=computed(()=>longestSavedLeg(props.itinerary))
const reasons={improved:'在保留所设条件的前提下，已采用交通或每日负担更合适的真实方案。',feasible_candidate:'原方案不满足时段或交通上限，备选方案已满足所设条件；不代表所有指标都改善。',baseline_preferred:'已核验的候选没有同时改善路途负担，保留原方案。',no_eligible_candidate:'没有找到符合相关性和用户输入保护条件的额外候选，保留原方案。',tool_budget_limited:'本次查询额度内没有可追加核验的候选，保留原方案。',no_transport_legs:'本次没有需要核验的交通路段，未为比较地点增加路线查询。'}
</script>
<template>
  <section v-if="summary" class="planning-comparison" aria-label="地点与路线对比">
    <div class="comparison-title"><strong>地点与路线对比</strong><span>{{summary.applied?'已采用备选方案':'保留原方案'}}</span></div>
    <p>{{reasons[summary.reason]}}</p>
    <div class="comparison-table"><table><caption>同一任务真实路线核验 · 含所选出发与返回</caption><thead><tr><th scope="col">指标</th><th scope="col">原方案</th><th scope="col">本次采用</th></tr></thead><tbody>
      <tr><th scope="row">交通总时间</th><td>{{summary.baseline.travel_minutes}} 分钟</td><td>{{summary.result.travel_minutes}} 分钟</td></tr>
      <tr><th scope="row">最长一段</th><td>{{summary.baseline.longest_leg_minutes==null?'无路段':`${summary.baseline.longest_leg_minutes} 分钟`}}</td><td>{{summary.result.longest_leg_minutes==null?'无路段':`${summary.result.longest_leg_minutes} 分钟`}}</td></tr>
      <tr><th scope="row">最忙一天总时长</th><td>{{summary.baseline.busiest_day_minutes}} 分钟</td><td>{{summary.result.busiest_day_minutes}} 分钟</td></tr>
      <tr><th scope="row">道路距离</th><td>{{summary.baseline.distance_km.toFixed(2)}} km</td><td>{{summary.result.distance_km.toFixed(2)}} km</td></tr>
    </tbody></table></div>
    <p v-if="!summary.baseline.feasible">原方案不满足所设条件，仅作对照，不是可采用的已保存行程。</p>
    <ul v-if="changes.length"><li v-for="change in changes" :key="change.day">第 {{change.day}} 天：<template v-if="change.removed.length||change.added.length"><span v-if="change.removed.length">移出 {{change.removed.join('、')}}；</span><span v-if="change.added.length">加入 {{change.added.join('、')}}</span></template><template v-else>站点顺序调整</template></li></ul>
    <details v-if="ratings.length" aria-label="地点评分取舍"><summary>地点评分取舍</summary><ul><li v-for="(poi,index) in ratings" :key="index">{{poi.kind}} · {{poi.name}}：接口评分 {{poi.rating==null?'未知':poi.rating}}</li></ul><p>评分来自接口，缺失保持未知，不代表到访体验。此项比较以路途为重点，采用地点的评分可能降低；可编辑原方案后重新核验。</p></details>
    <button v-if="summary.applied&&summary.baseline.feasible" type="button" class="secondary" :disabled="disabled" @click="emit('baseline')">编辑原方案</button>
    <button v-if="longest" type="button" class="secondary" :disabled="disabled" @click="emit('locate',longest.day,longest.id)">定位最长路段 · 第 {{longest.day+1}} 天</button>
    <details><summary>比较范围与数据依据</summary><p>同次真实搜索包含 {{summary.search_poi_count}} 个地点，额外核验 {{summary.candidates?.length??0}} 个候选。{{summary.budget_pruned_count?`${summary.budget_pruned_count} 个候选因查询额度未核验。`:''}}只比较有限方案，不保证全局最优；未核验候选不作为推荐结果。</p><p>原方案和采用方案使用同任务查询的真实路线。停留、时段和交通模式来自用户；未验证未来营业、预约和实际路况，费用缺失仍未知。编辑只调整用户选定的地点，不自动替换。</p></details>
  </section>
</template>
<style scoped>
.planning-comparison{padding:18px 24px;background:#f5f8f3;border-bottom:1px solid var(--line);font-size:12px;min-width:0}.comparison-title{display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap}.comparison-title span{color:var(--green)}p,li{line-height:1.8;color:var(--muted)}.comparison-table{overflow-x:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:left;font-size:12px}caption{text-align:left;padding:8px 0;color:var(--muted);font-size:11px}th,td{padding:9px 6px;border-top:1px solid var(--line);font-weight:400}thead th{font-weight:600}td:last-child{color:var(--green);font-weight:600}details{margin-top:14px}summary{cursor:pointer}ul{padding-left:18px}@media(max-width:680px){.planning-comparison{padding:16px}}
</style>
