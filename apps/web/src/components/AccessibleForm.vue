<script setup lang="ts">
import { nextTick, onBeforeUnmount, onUpdated, ref, useId } from 'vue'

const props=defineProps<{label:string;beforeFocus?:(field:HTMLElement)=>void|Promise<void>}>()
const emit=defineEmits<{submit:[event:SubmitEvent]}>()
type Field=HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement
const form=ref<HTMLFormElement>(),summary=ref<HTMLElement>()
const errors=ref<{id:string;label:string;message:string;field:Field}[]>([])
const prefix=useId()
let submitted=false
const descriptions=new Map<Field,string|null>()
function message(field:Field):string {
  const v=field.validity
  const type=field.getAttribute('type')??field.type
  if(v.badInput)return type==='number'?'请输入有效数字':'请完整填写此项'
  if(v.valueMissing)return '请填写此项'
  if(v.rangeUnderflow)return `不得小于 ${field.getAttribute('min')}`
  if(v.rangeOverflow)return `不得大于 ${field.getAttribute('max')}`
  if(v.stepMismatch)return type==='time'?'请按整分钟填写时间':field.getAttribute('step')==='1'||!field.getAttribute('step')?'请输入整数':'请检查数值精度'
  if(v.tooShort)return `至少填写 ${field.getAttribute('minlength')} 个字符`
  if(v.tooLong)return `最多填写 ${field.getAttribute('maxlength')} 个字符`
  if(v.patternMismatch||v.typeMismatch)return '请检查输入格式'
  if(!v.valid)return field.validationMessage
  if(field.required&&!field.value.trim())return '不能只填写空格'
  // Some browser ports expose date/time controls as text; keep the API's format here too.
  if(type==='time'&&field.value&&!/^([01]\d|2[0-3]):[0-5]\d$/.test(field.value))return '请按整分钟填写时间'
  if(type==='date'&&field.value) {
    const date=new Date(`${field.value}T00:00:00.000Z`)
    if(!/^\d{4}-\d{2}-\d{2}$/.test(field.value)||field.value.startsWith('0000')||!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==field.value)return '请填写有效日期（YYYY-MM-DD）'
  }
  const after=field.dataset.after,other=after?form.value?.elements.namedItem(after):null
  if(other instanceof HTMLInputElement&&field.value&&other.value&&field.value<=other.value)return '每日结束时间须晚于开始时间'
  return ''
}
function clearAnnotations() {
  for(const [field,description] of descriptions) {
    field.removeAttribute('aria-invalid')
    if(description===null)field.removeAttribute('aria-describedby');else field.setAttribute('aria-describedby',description)
  }
  descriptions.clear()
}
function collect() {
  clearAnnotations()
  const fields=Array.from(form.value?.elements??[]).filter((field):field is Field=>field instanceof HTMLInputElement||field instanceof HTMLSelectElement||field instanceof HTMLTextAreaElement)
  const next=fields.filter(field=>field.willValidate&&field.dataset.skipValidation!=='true').flatMap((field,index)=>{
    const text=message(field)
    if(!text)return []
    const id=`${prefix}-error-${index}`
    descriptions.set(field,field.getAttribute('aria-describedby'))
    field.setAttribute('aria-invalid','true')
    field.setAttribute('aria-describedby',[field.getAttribute('aria-describedby'),id].filter(Boolean).join(' '))
    return [{id,label:field.dataset.label||field.getAttribute('aria-label')||field.labels?.[0]?.childNodes[0]?.textContent?.trim()||'输入项',message:text,field}]
  })
  if(next.length!==errors.value.length||next.some((item,index)=>['id','label','message','field'].some(key=>item[key as keyof typeof item]!==errors.value[index]?.[key as keyof typeof item])))errors.value=next
}
async function focus(field:Field) {
  await props.beforeFocus?.(field)
  await nextTick()
  let ancestor=field.parentElement
  while(ancestor&&ancestor!==form.value){if(ancestor instanceof HTMLDetailsElement)ancestor.open=true;ancestor=ancestor.parentElement}
  field.focus();field.scrollIntoView({block:'center'})
}
async function submit(event:SubmitEvent) {
  submitted=true;collect()
  if(errors.value.length){await nextTick();summary.value?.focus();return}
  reset() // A later programmatic reset (for example a cleared password) is not a new invalid submission.
  emit('submit',event)
}
async function input() {if(submitted){await nextTick();collect()}}
function reset() {submitted=false;clearAnnotations();errors.value=[]}
defineExpose({reset})
onBeforeUnmount(clearAnnotations)
onUpdated(()=>{if(submitted)collect()})
</script>

<template>
  <form ref="form" novalidate :aria-label="label" @submit.prevent="submit" @input="input" @change="input">
    <section v-if="errors.length" ref="summary" class="form-errors" role="alert" tabindex="-1" :aria-label="`${label}错误`">
      <p>请检查以下 {{errors.length}} 项，再提交：</p>
      <ul><li v-for="item in errors" :id="item.id" :key="item.id"><button type="button" @click="focus(item.field)">{{item.label}}：{{item.message}}</button></li></ul>
    </section>
    <slot/>
  </form>
</template>
