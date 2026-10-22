<script setup lang="ts">
import type { Itinerary, Task } from '../api'
defineProps<{task:Task|null;itinerary:Itinerary|null;editing:boolean;dirty:boolean;active:boolean}>()
const emit=defineEmits<{locate:[step:'request'|'execution'|'itinerary']}>()
</script>

<template>
  <nav class="workflow-navigation" aria-label="规划流程">
    <button type="button" aria-label="填写需求" aria-controls="planning-form-title" @click="emit('locate','request')"><span>01</span><strong>填写需求</strong><small>必填、逐日与可选条件</small></button>
    <button type="button" aria-label="查看执行状态" aria-controls="execution-title" @click="emit('locate','execution')"><span>02</span><strong>查看执行状态</strong><small>{{active?'任务处理中，可查看或取消':task?'查看本次任务和失败条件':'提交后跟随真实进度'}}</small></button>
    <button type="button" aria-label="查看行程与调整" aria-controls="itinerary-title" @click="emit('locate','itinerary')"><span>03</span><strong>查看行程与调整</strong><small>{{dirty?'存在未保存修改':editing?'正在编辑，保存生成新版本':itinerary?'地图、多日时间轴与来源版本':'结果将在这里展开'}}</small></button>
  </nav>
</template>

<style scoped>
.workflow-navigation{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 20px}.workflow-navigation button{display:grid;grid-template-columns:auto 1fr;gap:5px 12px;text-align:left;border:1px solid var(--line);border-radius:9px;padding:13px 16px;background:#fff;min-width:0}.workflow-navigation span{grid-row:span 2;font-size:11px;color:var(--green);align-self:center}.workflow-navigation strong{font-size:12px;font-weight:600}.workflow-navigation small{line-height:1.6;overflow-wrap:anywhere}@media(max-width:680px){.workflow-navigation{grid-template-columns:1fr;gap:7px}.workflow-navigation button{padding:10px 13px}.workflow-navigation small{grid-column:2}}
</style>
