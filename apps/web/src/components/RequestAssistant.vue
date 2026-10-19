<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { Draft, Schema } from '../api'
import { clarificationRequest, draftFields, type DraftField } from '../draft'

const props=defineProps<{draft:Draft|null;capability:Schema<'Capabilities'>|null;disabled:boolean;conflict:boolean}>()
const emit=defineEmits<{parse:[text:string];apply:[draft:Draft];clarify:[request:Schema<'DraftClarificationRequest'>];reload:[]}>()
const text=ref('')
const answers=reactive<Partial<Record<DraftField,string|number>>>({})
const selected=reactive<Partial<Record<DraftField,boolean>>>({})
const localError=ref('')
watch(()=>props.draft,(value,previous)=>{
  if(value&&value.id!==previous?.id) text.value=value.input.text
  for(const field of draftFields) {answers[field.key]=String(value?.proposal.values[field.key]??'');selected[field.key]=false}
  localError.value=''
},{immediate:true})
const canParse=computed(()=>props.capability?.draft_enabled && props.capability?.helloagents_available && props.capability?.llm_configured)
const fieldNames:Record<string,string>={city:'目的地',query:'地点关键词',start_date:'出发日期',days:'天数',stops_per_day:'每天站数',day_start:'每日开始',day_end:'每日结束',stay_minutes:'每站停留',mode:'交通方式',budget:'预算上限'}
const fields=computed(()=>Object.entries(props.draft?.proposal.values??{}).filter(([,value])=>value!==null))
function display(name:string,value:unknown) {return name==='mode'?(value==='walking'?'步行':'驾车'):String(value)}
function save() {
  if(!props.draft) return
  try {localError.value='';emit('clarify',clarificationRequest(props.draft,answers,selected))}
  catch(error) {localError.value=error instanceof Error?error.message:'请检查补充字段'}
}
function selectFilled() {for(const field of draftFields) selected[field.key]=Boolean(String(answers[field.key]??'').trim())}
</script>

<template>
  <section class="card request-assistant">
    <div class="section-title"><div><div class="eyebrow">TELL US YOUR PLAN</div><h2>用一句话，整理旅行需求</h2></div><span class="subtle">先整理，再核对</span></div>
    <form @submit.prevent="emit('parse',text)">
      <label for="travel-description">旅行需求<textarea id="travel-description" v-model="text" rows="3" maxlength="2000" required :disabled="disabled" placeholder="例如：10月20日去杭州玩两天，想逛博物馆，每天三站，步行，预算800元"/></label>
      <div class="assistant-actions"><p>{{draft?'重新整理会创建新草案；补充现有需求请使用下方核对区。':'整理目的地、日期与约束，核对表单后再查询真实路线。'}}</p><button class="secondary" type="submit" :disabled="disabled||!canParse||!text.trim()">{{draft?'创建新草案 ↗':'整理为草案 ↗'}}</button></div>
    </form>
    <p v-if="capability&&!canParse" class="assistant-note">需求解析服务尚未启用，可直接填写左侧规划表单。</p>
    <div v-if="draft" class="draft-review">
      <div class="section-title"><h3>待核对的需求草案</h3><span class="status-pill">第 {{draft.revision??1}} 版 · {{draft.questions.length?'需要补全':'待核对'}}</span></div>
      <p class="draft-original">{{draft.input.text}}</p>
      <dl class="draft-fields"><template v-for="([name,value]) in fields" :key="name"><dt>{{fieldNames[name]||name}}</dt><dd>{{display(name,value)}}<small>{{draft.field_sources?.[name as DraftField]==='user_input'?'用户填写':'原文'}}：{{draft.proposal.evidence[name]}}</small><small>{{draft.confirmed_fields?.includes(name as DraftField)?'已确认':'待确认'}}</small></dd></template></dl>
      <ul v-if="draft.questions.length" class="warning-list"><li v-for="question in draft.questions" :key="question">{{question}}</li></ul>
      <details class="clarification-panel" :open="draft.questions.length>0">
        <summary>核对与补充字段</summary>
        <p class="assistant-note">填写或勾选要保存的字段；未勾选的内容会保留。空值表示未说明，表单默认值不会成为已确认需求。</p>
        <form @submit.prevent="save">
          <fieldset :disabled="disabled||conflict" class="clarification-fields">
            <div v-for="field in draftFields" :key="field.key" class="clarification-field">
              <label :for="`draft-${field.key}`">{{field.label}}<small v-if="draft.confirmed_fields?.includes(field.key)">已确认</small></label>
              <select v-if="field.key==='mode'" :id="`draft-${field.key}`" v-model="answers[field.key]" :aria-label="`草案${field.label}`" @change="selected[field.key]=true"><option value="">未说明</option><option value="walking">步行</option><option value="driving">驾车</option></select>
              <input v-else :id="`draft-${field.key}`" v-model="answers[field.key]" :aria-label="`草案${field.label}`" :type="field.type" :min="field.min" :max="field.max" :step="field.key==='budget'?'any':1" :maxlength="field.key==='city'?60:240" placeholder="未说明" @input="selected[field.key]=true"/>
              <label class="clarification-check"><input v-model="selected[field.key]" type="checkbox" :aria-label="`保存${field.label}`"/>保存此项</label>
            </div>
          </fieldset>
          <p v-if="localError" role="alert" class="clarification-error">{{localError}}</p>
          <div class="assistant-actions"><button type="button" class="text-button" :disabled="disabled||conflict" @click="selectFilled">选中全部已填写字段</button><button type="submit" class="secondary" :disabled="disabled||conflict">保存补充与确认 ↗</button></div>
        </form>
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
