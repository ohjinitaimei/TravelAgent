<script setup lang="ts">
import type { Task, TravelEvent } from '../api'
import TimeConstraintGuide from './TimeConstraintGuide.vue'
import TravelLoadPanel from './TravelLoadPanel.vue'
defineProps<{task:Task|null;events:TravelEvent[];taskActive:boolean;busy:boolean;pending:boolean;restoring:boolean;editing:boolean;timeGuideEditable:boolean;travelGuideEditable:boolean}>()
const emit=defineEmits<{cancel:[];resume:[];retry:[event:MouseEvent];time:[field:'window'|'stops'|'stay',day:number];limits:[]}>()
const statusLabels:Record<string,string>={queued:'排队中',running:'规划中',succeeded:'已完成',failed:'失败',cancelled:'已取消',timed_out:'已超时'}
function eventTime(value?:string){return value?new Date(value).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'时间未提供'}
</script>
<template>
<section class="card execution"><div class="section-title"><h2 id="execution-title" tabindex="-1">{{task?.kind==='draft'?'需求整理过程':'规划过程'}} <span v-if="task" class="status-pill" :class="task.status">{{task.status==='running'&&task.kind==='draft'?'整理中':statusLabels[task.status]}}</span></h2><button v-if="taskActive" class="text-button" @click="emit('cancel')">取消任务</button></div>
            <div v-if="!task" class="execution-empty"><span>◷</span>提交需求后，在这里查看真实执行进度。</div>
            <ol v-else class="event-list"><li v-for="event in events" :key="event.id"><span class="event-dot"/><span>{{event.message}}</span><time>{{eventTime(event.timestamp)}}</time></li></ol>
            <div v-if="task" class="task-controls"><small class="task-id">任务 {{task.id}}<span v-if="task.retry_of"> · 原任务重试</span></small><button v-if="!busy&&!pending" class="text-button" @click="emit('resume')">重新查询状态 ↻</button><button v-if="task.retry_available&&!pending" class="secondary" :disabled="busy" @click="emit('retry',$event)">按原条件重试</button></div>
            <p v-if="task?.error?.retry_after" role="status" aria-label="数据请求等待提示">服务建议等待约 {{task.error.retry_after}} 秒后手动重试；不会自动重新提交规划，等待后也可能仍受限。</p>
            <TimeConstraintGuide v-if="task?.status==='failed'&&task.error?.code==='time_constraint_exceeded'" :details="task.error.time_constraints" :editable="timeGuideEditable" :editing="editing" @locate="(field,day)=>emit('time',field,day)"/>
            <TravelLoadPanel v-if="task?.status==='failed'&&task.error?.code==='travel_constraint_exceeded'" failure :details="task.error.travel_constraints" :editable="travelGuideEditable" :editing="editing" @limits="emit('limits')"/>
            <small v-if="restoring" role="status">正在恢复上次的工作空间…</small>
          </section>
</template>
