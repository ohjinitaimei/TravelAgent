<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import AccessibleForm from './AccessibleForm.vue'
import DraftDailyReview from './DraftDailyReview.vue'
import { intakeStatus } from '../serviceStatus'
import type { Draft, Schema } from '../api'
import { clarificationRequest, displayDraftValue, draftFields, type DraftDayInput, type DraftField, type ScalarDraftField } from '../draft'
import { requirementsReview, requirementsSourceMatches, requirementsText, selectRequirementsFilled, setRequirementsAnswer, setRequirementsSchedules, setRequirementsSelected, setRequirementsText, type RequirementsInput } from '../requirementsInput'

const props=defineProps<{input:RequirementsInput;draft:Draft|null;capability:Schema<'Capabilities'>|null;serviceCurrent:boolean;disabled:boolean;conflict:boolean}>()
const emit=defineEmits<{'update:input':[value:RequirementsInput];parse:[text:string];apply:[draft:Draft];clarify:[request:Schema<'DraftClarificationRequest'>];reload:[]}>()
const text=computed(()=>requirementsText(props.input,props.draft))
const review=computed(()=>props.draft?requirementsReview(props.input,props.draft):null)
const sourceMismatch=computed(()=>!requirementsSourceMatches(props.input,props.draft)||Boolean(props.draft&&props.input.clarification&&!review.value))
const answers=computed(()=>review.value?.answers??{})
const scheduleAnswers=computed(()=>review.value?.schedules??null)
const selected=computed(()=>review.value?.selected??{})
const localError=ref(''),localErrorElement=ref<HTMLElement>()
watch(()=>props.draft,()=>{localError.value=''})
const intake=computed(()=>intakeStatus(props.capability,props.serviceCurrent))
const canParse=computed(()=>intake.value.enabled)
const fieldNames:Record<string,string>={...Object.fromEntries(draftFields.map(field=>[field.key,field.label])),day_schedules:'逐日时段与默认停留'}
const fields=computed(()=>Object.entries(props.draft?.proposal.values??{}).filter(([,value])=>value!=null))
function save() {
  if(!props.draft) return
  if(sourceMismatch.value){localError.value='未保存补充与当前草案版本不一致，请先核对或放弃原补充。';return}
  try {localError.value='';emit('clarify',clarificationRequest(props.draft,answers.value,selected.value,scheduleAnswers.value))}
  catch(error) {localError.value=error instanceof Error?error.message:'请检查补充字段';void nextTick(()=>localErrorElement.value?.focus())}
}
function changeText(event:Event){emit('update:input',setRequirementsText(props.input,(event.target as HTMLTextAreaElement).value))}
function changeAnswer(key:ScalarDraftField,event:Event){if(props.draft&&!sourceMismatch.value)emit('update:input',setRequirementsAnswer(props.input,props.draft,key,(event.target as HTMLInputElement).value))}
function changeSelected(key:DraftField,value:boolean){if(props.draft&&!sourceMismatch.value)emit('update:input',setRequirementsSelected(props.input,props.draft,key,value))}
function changeSchedules(value:DraftDayInput[]|null){if(props.draft&&!sourceMismatch.value)emit('update:input',setRequirementsSchedules(props.input,props.draft,value))}
function selectFilled(){if(props.draft&&!sourceMismatch.value)emit('update:input',selectRequirementsFilled(props.input,props.draft))}
</script>

<template>
  <section class="card request-assistant">
    <div class="section-title"><div><div class="eyebrow">TELL US YOUR PLAN</div><h2>用一句话，整理旅行需求</h2></div><span class="subtle">先整理，再核对</span></div>
    <AccessibleForm label="旅行需求整理" @submit="emit('parse',text)">
      <label for="travel-description">旅行需求<textarea id="travel-description" :value="text" rows="3" maxlength="2000" required :disabled="disabled" placeholder="例如：10月20日去杭州玩两天，想逛博物馆，每天三站，步行，预算800元" @input="changeText"/></label>
      <div class="assistant-actions"><p>{{draft?'重新整理会创建新草案；补充现有需求请使用下方核对区。':'整理目的地、日期与约束，核对表单后再查询真实路线。'}}</p><button class="secondary" type="submit" :disabled="disabled||!canParse||!text.trim()">{{draft?'创建新草案 ↗':'整理为草案 ↗'}}</button></div>
    </AccessibleForm>
    <p class="assistant-note">相对日期按提交时的北京时间理解，生成后请核对具体日期。</p>
    <p v-if="!canParse" role="status" class="assistant-note">{{intake.label}}。{{intake.detail}}</p>
    <div v-if="draft" class="draft-review">
      <div class="section-title"><h3>待核对的需求草案</h3><span class="status-pill">第 {{draft.revision??1}} 版 · {{draft.questions.length?'需要补全':'待核对'}}</span></div>
      <p class="draft-original">{{draft.input.text}}</p>
      <p class="assistant-note">本份草案的参考日期：{{draft.input.reference_date}}（北京时间）。</p>
      <dl class="draft-fields"><template v-for="([name,value]) in fields" :key="name"><dt>{{fieldNames[name]||name}}</dt><dd>{{displayDraftValue(name,value)}}<small>{{draft.field_sources?.[name as DraftField]==='user_input'?'用户填写':'原文'}}：{{draft.proposal.evidence[name]}}</small><small>{{draft.confirmed_fields?.includes(name as DraftField)?(name==='day_schedules'?'所填内容已确认，空项仍需补全':'已确认'):'待确认'}}</small></dd></template></dl>
      <p v-if="draft.proposal.values.origin_hint||draft.proposal.values.destination_hint" class="assistant-note">出发与返回仅保留用户地点线索。填入表单后须在出发与返回区域搜索并选择真实地点；线索不会自动成为地点 ID 或路线。</p>
      <ul v-if="draft.questions.length" class="warning-list"><li v-for="question in draft.questions" :key="question">{{question}}</li></ul>
      <div v-if="sourceMismatch&&input.clarification" role="region" aria-label="保留的需求补充" class="draft-conflict requirement-source-conflict">
        <p>未保存补充来自草案 #{{input.clarification.sourceId}} 第 {{input.clarification.sourceRevision}} 版，未套用到当前草案。请先核对或放弃原补充；填写内容仍保留。</p>
        <p v-if="Object.values(input.clarification.selected).some(Boolean)">已勾选待保存：{{Object.entries(input.clarification.selected).filter(([,selected])=>selected).map(([key])=>fieldNames[key]||key).join('、')}}。这些选择未确认到当前版本。</p>
        <dl class="draft-fields"><template v-for="(value,key) in input.clarification.answers" :key="key"><dt>{{fieldNames[key]||key}}</dt><dd>{{value===''?'明确清空':value}}</dd></template></dl>
        <p v-if="input.clarification.schedulePatch?.count===null">逐日安排：明确清空。</p>
        <p v-else-if="input.clarification.schedulePatch?.count">逐日项数量：{{input.clarification.schedulePatch.count}} 天。</p>
        <template v-for="(day,index) in input.clarification.schedulePatch?.days" :key="index"><p>第 {{Number(index)+1}} 天修改：<span v-for="(value,key) in day" :key="key">{{key==='day_start'?'开始':key==='day_end'?'结束':'停留'}} {{value===''||value===null?'明确清空':value}}；</span></p></template>
      </div>
      <details class="clarification-panel" :open="draft.questions.length>0">
        <summary>核对与补充字段</summary>
        <p class="assistant-note">填写或勾选要保存的字段；未勾选的内容会保留。空值表示未说明，表单默认值不会成为已确认需求。</p>
        <AccessibleForm label="草案补充" @submit="save">
          <fieldset :disabled="disabled||conflict||sourceMismatch" class="clarification-fields">
            <div v-for="field in draftFields" :key="field.key" class="clarification-field">
              <label :for="`draft-${field.key}`">{{field.label}}<small v-if="draft.confirmed_fields?.includes(field.key)">已确认</small></label>
              <select v-if="field.key==='mode'" :id="`draft-${field.key}`" :value="answers[field.key]" :aria-label="`草案${field.label}`" @change="changeAnswer(field.key,$event)"><option value="">未说明</option><option value="walking">步行</option><option value="driving">驾车</option></select>
              <input v-else :id="`draft-${field.key}`" :value="answers[field.key]" :data-skip-validation="!selected[field.key]" :aria-label="`草案${field.label}`" :type="field.type" :min="field.min" :max="field.max" :step="field.type==='time'?60:field.key==='budget'?'any':1" :maxlength="field.maxlength??(field.key==='city'?60:240)" placeholder="未说明" @input="changeAnswer(field.key,$event)"/>
              <label class="clarification-check"><input :checked="selected[field.key]" type="checkbox" :aria-label="`保存${field.label}`" @change="changeSelected(field.key,($event.target as HTMLInputElement).checked)"/>保存此项</label>
            </div>
          </fieldset>
          <DraftDailyReview :value="scheduleAnswers" :count="Number(answers.days)||1" :selected="Boolean(selected.day_schedules)" :disabled="disabled||conflict||sourceMismatch" @change="changeSchedules" @select="changeSelected('day_schedules',$event)"/>
          <p v-if="localError" ref="localErrorElement" tabindex="-1" role="alert" class="clarification-error">{{localError}}</p>
          <div class="assistant-actions"><button type="button" class="text-button" :disabled="disabled||conflict||sourceMismatch" @click="selectFilled">选中全部已填写字段</button><button type="submit" class="secondary" :disabled="disabled||conflict||sourceMismatch">保存补充与确认 ↗</button></div>
        </AccessibleForm>
      </details>
      <div v-if="conflict" class="draft-conflict" role="alert"><p>本次补充尚未保存。请记下补充内容，加载最新草案后重新核对。</p><button class="secondary" :disabled="disabled" @click="emit('reload')">加载最新草案（替换未保存补充）</button></div>
      <p v-if="draft.clarifications?.length" class="assistant-note">已保存 {{draft.clarifications.length}} 次补充。更新草案后，请重新填入规划表单并核对。</p>
      <div v-if="draft.proposal.unhandled_requirements?.length" class="draft-unhandled"><strong>仍需人工处理的要求</strong><ul class="warning-list"><li v-for="item in draft.proposal.unhandled_requirements" :key="item">{{item}}</li></ul></div>
      <p v-for="warning in draft.warnings" :key="warning" class="assistant-note">{{warning}}</p>
      <button class="primary" :disabled="disabled" @click="emit('apply',draft)">填入表单并核对 ↗</button>
    </div>
  </section>
</template>

<style scoped>
.clarification-panel{border:1px solid var(--line);border-radius:10px;padding:16px;margin:18px 0}
.clarification-panel summary{cursor:pointer;font-weight:600;font-size:13px}
.clarification-panel .assistant-note{margin:12px 0}
.clarification-fields{border:0;padding:0;margin:16px 0;display:grid;grid-template-columns:1fr 1fr;gap:14px 18px;min-width:0}
.clarification-field{min-width:0}
.clarification-field>label{margin:0 0 6px}
.clarification-field>label small{display:inline;margin-left:8px;color:var(--green)}
.clarification-field .clarification-check{display:flex;align-items:center;gap:6px;margin:6px 0 0;font-size:11px}
.clarification-check input{width:auto;margin:0;accent-color:var(--green)}
.clarification-error,.draft-conflict p{color:#a24e32;font-size:12px;margin:12px 0}
.draft-conflict{border:1px solid #e3c8bb;padding:12px;border-radius:8px;margin:12px 0}
@media(max-width:680px){.clarification-fields{grid-template-columns:1fr}}
</style>
