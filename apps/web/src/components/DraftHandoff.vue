<script setup lang="ts">
import { computed } from 'vue'
import type { Draft } from '../api'
import type { PlanForm } from '../schedules'
import { handoffAccepted, handoffAnchorsReady, needsHandoff, type HandoffDecision } from '../handoff'
const props=defineProps<{draft:Draft;form:PlanForm;decision:HandoffDecision|null;disabled:boolean}>()
const emit=defineEmits<{decision:[policy:HandoffDecision['policy']];locate:[]}>()
const accepted=computed(()=>handoffAccepted(props.draft,props.form,props.decision))
const ready=computed(()=>handoffAnchorsReady(props.draft,props.form))
</script>

<template>
  <section class="draft-handoff" aria-label="草案到规划核对">
    <h3>按当前表单规划</h3>
    <p>已填入第 {{draft.revision??1}} 版草案。未表达的选项采用表单默认，仍可手动修改；上方条件才是本次提交依据。</p>
    <template v-if="needsHandoff(draft)">
      <p>原文出发地：{{draft.proposal.values.origin_hint||'未说明'}}；返回地：{{draft.proposal.values.destination_hint||'未说明'}}。</p>
      <p>地点文字尚未绑定真实地点。请核对每一天的真实搜索选择，或明确只按表单条件规划。</p>
      <div class="handoff-actions">
        <button type="button" class="text-button" :disabled="disabled" @click="emit('locate')">搜索并选择起终点</button>
        <button type="button" class="secondary" :disabled="disabled||!ready" @click="emit('decision','selected')">确认已选起终点</button>
        <button type="button" class="secondary" :disabled="disabled" @click="emit('decision','form_only')">本次仅按表单条件规划</button>
      </div>
      <p role="status">{{accepted?(decision?.policy==='selected'?'已确认当前真实地点选择；系统不推断它与原文是否相同。':'已明确仅按当前表单规划，未选择的原文起终点不计入路线。'):'请先处理原文起终点，再开始规划。'}}</p>
    </template>
    <div v-if="draft.proposal.unhandled_requirements?.length"><strong>仍需人工处理</strong><ul><li v-for="item in draft.proposal.unhandled_requirements" :key="item">{{item}}</li></ul><p>这些要求不属于本次算法已验证的约束，保存行程不代表它们已满足。</p></div>
  </section>
</template>

<style scoped>
.draft-handoff{grid-column:1/-1;min-width:0;background:#f4f7ef;border:1px solid var(--line);border-radius:9px;padding:12px;margin-bottom:16px}.draft-handoff h3{font-size:13px}.draft-handoff p,.draft-handoff ul,.draft-handoff strong{font-size:11px;line-height:1.8;overflow-wrap:anywhere}.draft-handoff p{margin-top:8px}.draft-handoff ul{padding-left:18px}.handoff-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.handoff-actions .secondary{font-size:11px;padding:8px}
</style>
