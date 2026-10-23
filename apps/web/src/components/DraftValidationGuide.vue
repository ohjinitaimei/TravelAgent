<script setup lang="ts">
import type { Schema } from '../api'
defineProps<{details:Schema<'DraftValidationDiagnostics'>}>()
const fields:Record<string,string>={submission:'需求草案',values:'需求条件',evidence:'原文依据',unhandled_requirements:'未处理要求',city:'城市',query:'搜索关键词',start_date:'出发日期',days:'天数',stops_per_day:'每天站数',day_start:'开始时间',day_end:'结束时间',stay_minutes:'停留分钟',mode:'交通方式',budget:'预算',day_schedules:'逐日安排',max_leg_travel_minutes:'单段交通上限',max_daily_travel_minutes:'每日交通上限',origin_hint:'出发地提示',destination_hint:'返回地提示'}
const reasons:Record<string,string>={missing:'缺少必要字段',type:'字段类型不符合要求',range:'数值或数量超出允许范围',format:'格式不符合要求',constraint:'条件之间存在冲突或不符合约束',unexpected_field:'包含不支持的字段',ungrounded:'缺少对应的用户原文依据'}
function label(path:string){const p=path.split('.');if(p[1]==='day_schedules'&&p[2]!==undefined)return `第 ${Number(p[2])+1} 天${p[3]?fields[p[3]]:'安排'}`;return fields[p[1]??p[0]]??'需求条件'}
</script>
<template>
  <section class="notice" role="status" aria-label="需求校验提示">
    <strong>需求整理未通过校验</strong>
    <ul><li v-for="(issue,index) in details.issues" :key="index">{{label(issue.path)}}：{{reasons[issue.reason]}}</li></ul>
    <p>这些提示来自模型返回内容的校验，不代表你填写有误。原文已保留，可修改描述后手动整理，或直接填写下方规划表单。</p>
  </section>
</template>
