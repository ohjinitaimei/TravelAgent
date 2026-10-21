<script setup lang="ts">
import { computed } from 'vue'
import type { Itinerary } from '../api'
import { shortVersion, versionChanges, versionMetrics } from '../versions'
const props=defineProps<{parent:Itinerary;child:Itinerary}>()
const changes=computed(()=>versionChanges(props.parent,props.child))
const rows=computed(()=>{
  const before=versionMetrics(props.parent),after=versionMetrics(props.child)
  const minute=(value:number|null)=>value===null?'交通数据不完整':`${value} 分钟`
  const distance=(value:number|null)=>value===null?'交通数据不完整':`${value.toFixed(2)} km`
  const total=(value:number|null)=>value==null?'未知':`¥${value.toFixed(2)}`
  return [
    ['地点',`${before.stops} 站`,`${after.stops} 站`],['用户设定停留',minute(before.stay),minute(after.stay)],
    ['已保存站间交通',minute(before.travel),minute(after.travel)],['已保存道路距离',distance(before.distance),distance(after.distance)],
    ['已录入费用小计',total(before.knownCost),total(after.knownCost)],
    ['站点费用未填',`${before.missingStationCosts} 站`,`${after.missingStationCosts} 站`],
    ['完整预算总额',total(before.totalCost),total(after.totalCost)]
  ]
})
</script>
<template>
  <div class="version-comparison">
    <div class="version-table"><table><caption>已保存事实：来源 #{{shortVersion(parent.id)}} → 调整 #{{shortVersion(child.id)}}</caption><thead><tr><th scope="col">项目</th><th scope="col">来源版本</th><th scope="col">调整版本</th></tr></thead><tbody><tr v-for="row in rows" :key="row[0]"><th scope="row">{{row[0]}}</th><td>{{row[1]}}</td><td>{{row[2]}}</td></tr></tbody></table></div>
    <div v-if="changes.length" class="version-table"><table><caption>已保存的地点与条件改动</caption><thead><tr><th scope="col">项目</th><th scope="col">来源版本</th><th scope="col">调整版本</th></tr></thead><tbody><tr v-for="(change,index) in changes" :key="index"><th scope="row">{{change.label}}</th><td>{{change.before}}</td><td>{{change.after}}</td></tr></tbody></table></div>
    <p v-else>地点顺序、停留、录入费用和所列条件相同；交通事实仍以各版本已保存结果为准。</p>
    <small>只读对照，不重新计算路线或修改行程。小计仅包含已录入费用，未知费用不等于免费；两个版本的交通获取时点可能不同。</small>
  </div>
</template>
<style scoped>
.version-table{overflow:auto;max-height:360px;margin:16px 0}.version-table table{border-collapse:collapse;width:100%;font-size:12px;min-width:340px}.version-table caption{text-align:left;padding:8px 0;color:var(--muted)}.version-table th,.version-table td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}.version-table tbody th{font-weight:500}.version-table td:last-child{color:var(--green)}small,p{font-size:12px;color:var(--muted);line-height:1.8;display:block}
</style>
