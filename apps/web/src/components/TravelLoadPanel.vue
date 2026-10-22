<script setup lang="ts">
import { computed } from 'vue'
import type { Schema } from '../api'
const props=defineProps<{report?:Schema<'TravelLoad'>|null;details?:Schema<'TravelConstraintDiagnostics'>|null;failure?:boolean;editable?:boolean;editing?:boolean}>()
const emit=defineEmits<{limits:[];day:[number]}>()
const value=computed(()=>props.details??props.report)
const modes={walking:'步行',driving:'驾车'}
const kinds={origin:'出发至首站',interstop:'站间',destination:'末站返回'}
const percent=new Intl.NumberFormat('zh-CN',{style:'percent',minimumFractionDigits:1,maximumFractionDigits:1})
</script>
<template>
  <section class="travel-load" :aria-label="failure?'交通约束调整建议':'路途负担'">
    <h3>{{failure?'所选交通上限需要调整':'路途负担'}}</h3>
    <template v-if="value">
      <p>{{failure?'失败任务原方案':'当前保存版本'}} · {{modes[value.mode]}}。单段上限：{{value.max_leg_travel_minutes==null?'未设置':`${value.max_leg_travel_minutes} 分钟`}}；每日上限：{{value.max_daily_travel_minutes==null?'未设置':`${value.max_daily_travel_minutes} 分钟`}}。包含所选出发及返回交通。</p>
      <div class="load-table"><table><caption>{{failure?'原方案交通核验':'已保存路线汇总'}}（分钟）</caption><thead><tr><th scope="col">日期</th><th scope="col">停留</th><th scope="col">交通</th><th scope="col">最长一段</th><th scope="col">交通占已排时间</th><th scope="col">提示</th></tr></thead>
        <tbody><tr v-for="day in value.days" :key="day.day_number"><th scope="row">第 {{day.day_number}} 天</th><td>{{day.stay_minutes}}</td><td>{{day.travel_minutes}}</td><td>{{day.longest_leg_minutes??'无路段'}}</td><td>{{percent.format(day.travel_share_of_scheduled)}}</td><td><span v-if="day.over_daily_minutes">每日超出 {{day.over_daily_minutes}} 分钟。 </span><span v-if="day.violating_legs?.length">{{day.violating_legs.length}} 段超上限。 </span><span v-if="day.travel_at_least_stay">交通不少于停留，请核对安排。</span><span v-else-if="!day.over_daily_minutes&&!day.violating_legs?.length">按自身情况核对</span><button v-if="!failure" type="button" class="text-button" :disabled="!editable" @click="emit('day',day.day_number)">查看第 {{day.day_number}} 天</button></td></tr></tbody></table></div>
      <ul v-if="failure"><template v-for="day in value.days" :key="day.day_number"><li v-for="leg in day.violating_legs" :key="`${leg.kind}:${leg.origin_id}:${leg.destination_id}`">第 {{day.day_number}} 天 · {{kinds[leg.kind]}}：{{leg.duration_min}} 分钟，超出 {{leg.overrun_minutes}} 分钟。</li></template></ul>
    </template>
    <p v-else>此历史记录未保存路途负担报告，可编辑并保存后由后端重新核验。</p>
    <p>比例以停留与已选交通之和为分母。未设置一侧的往返、站内步行、排队及未来路况未计入；没有提示也不代表体力负担适合你。</p>
    <template v-if="failure"><p>可减少或替换地点、修改交通方式，或按自己的意愿调整上限。扩大每日时段或缩短停留不会降低实际交通时长。</p><button type="button" class="secondary" :disabled="!editable" @click="emit('limits')">调整交通上限</button><small>只定位当前输入，不改值、不提交。{{editable?'修改后请重新提交核验。':'请先恢复原行程编辑草稿，或退出当前编辑再调整规划表单。'}}</small></template>
  </section>
</template>
<style scoped>
.travel-load{margin:16px 24px;padding:18px;border:1px solid var(--line);border-radius:10px;background:#f7f9f5;min-width:0}.travel-load h3{margin:0;font-size:15px}.travel-load p,.travel-load li{font-size:12px;line-height:1.8}.load-table{overflow-x:auto}.load-table table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}.load-table caption{text-align:left;padding:8px 0}.load-table td,.load-table th{padding:8px;text-align:left;border-bottom:1px solid var(--line)}.travel-load small{display:block;margin-top:10px;line-height:1.8;font-size:11px}.text-button{display:block}@media(max-width:680px){.travel-load{margin:12px 16px;padding:14px}}
</style>
