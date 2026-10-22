<script setup lang="ts">
import type { Schema } from '../api'

defineProps<{ details?: Schema<'TimeConstraintDiagnostics'> | null; editable: boolean; editing: boolean }>()
const emit = defineEmits<{ locate: [field: 'window' | 'stops' | 'stay', dayNumber: number] }>()
</script>

<template>
  <section class="time-guide" aria-label="时间约束调整建议">
    <h3>每天的时间需要再留一点余量</h3>
    <template v-if="details">
      <p>失败任务的原时段为 {{details.day_start}}–{{details.day_end}}，每天可用 {{details.available_minutes}} 分钟。下表显示原方案超时的日期，不是已保存行程或可行候选。</p>
      <div class="time-table"><table><caption>原方案时间核验（分钟）</caption><thead><tr><th scope="col">日期</th><th scope="col">停留</th><th scope="col">站间交通</th><th scope="col">出发交通</th><th scope="col">返回交通</th><th scope="col">共需</th><th scope="col">超出</th></tr></thead><tbody><tr v-for="day in details.days" :key="day.day_number"><th scope="row">第 {{day.day_number}} 天</th><td>{{day.stay_minutes}}</td><td>{{day.travel_minutes}}</td><td>{{day.origin_travel_minutes??0}}</td><td>{{day.destination_travel_minutes??0}}</td><td>{{day.required_minutes}}</td><td>{{day.overrun_minutes}}</td></tr></tbody></table></div>
      <p>停留取自该任务的用户设置，交通取自接口结果；出发/返回仅在选定对应地点时计入。未设置一侧的往返、预约或营业时间未验证，也不代表未来实际耗时。</p>
    </template>
    <p v-else>这条历史任务没有分日诊断。请核对每日时段、地点数量与停留时间，再重新提交。</p>
    <p>可以扩大每日时段，减少地点，或按自己的安排缩短停留。改变条件后仍需后端重新核验，不保证一次调整即可通过。</p>
    <div class="guide-actions"><button type="button" class="secondary" :disabled="!editable" @click="emit('locate','window',details?.days[0]?.day_number??1)">调整每日时段</button><button type="button" class="secondary" :disabled="!editable" @click="emit('locate','stops',details?.days[0]?.day_number??1)">{{editing?'调整当日地点':'调整每天站数'}}</button><button type="button" class="secondary" :disabled="!editable" @click="emit('locate','stay',details?.days[0]?.day_number??1)">调整停留时间</button></div>
    <small v-if="!editable&&details?.operation==='adjust'">请先恢复本机编辑草稿，或重新编辑原行程；失败没有修改已保存版本。</small>
    <small v-else-if="!editable&&editing">请先保存或退出当前编辑，再核对规划表单。</small>
    <small v-else>按钮只定位当前输入，不改值、不提交。诊断保留失败任务的原条件，不随当前表单变化；核对后点击{{editing?'“保存并重算”':'“开始规划”'}}创建新任务。</small>
  </section>
</template>

<style scoped>
.time-guide{margin:16px 24px 24px;padding:18px;border:1px solid #dec9a4;border-radius:10px;background:#fcf8ef;color:#55472d;min-width:0}.time-guide h3{margin:0 0 10px;font-size:15px}.time-guide p{font-size:12px;line-height:1.8;margin:10px 0}.time-table{overflow-x:auto;max-width:100%}.time-table table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:12px}.time-table caption{text-align:left;font-size:11px;padding:6px 0;color:#71634c}.time-table th,.time-table td{padding:9px 7px;text-align:left;border-bottom:1px solid #e7dcc7}.time-table td:last-child{font-weight:700;color:#8a3c25}.guide-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.time-guide small{display:block;font-size:11px;line-height:1.8;color:#71634c}@media(max-width:680px){.time-guide{margin:12px 16px 16px;padding:14px}.guide-actions button{flex:1 1 140px}}
</style>
