<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
const props=defineProps<{open:boolean;action:string}>()
const emit=defineEmits<{discard:[];keep:[]}>()
const dialog=ref<HTMLDialogElement>()
let previous:HTMLElement|null=null
watch(()=>props.open,async value=>{
  await nextTick()
  if(value&&dialog.value&&!dialog.value.open){previous=document.activeElement as HTMLElement;dialog.value.showModal()}
  else if(!value&&dialog.value?.open){dialog.value.close();previous?.isConnected&&previous.focus()}
},{immediate:true})
onBeforeUnmount(()=>dialog.value?.close())
</script>

<template>
  <dialog ref="dialog" class="discard-dialog" aria-labelledby="discard-title" aria-describedby="discard-description" @cancel.prevent="emit('keep')">
    <h2 id="discard-title">有未保存的行程修改</h2>
    <p id="discard-description">继续此操作会放弃本次编辑，已保存的行程保持原样。</p>
    <div><button autofocus class="secondary" @click="emit('keep')">继续编辑</button><button class="primary" @click="emit('discard')">{{action}}</button></div>
  </dialog>
</template>

<style scoped>
.discard-dialog{border:1px solid var(--line);border-radius:14px;padding:28px;width:min(440px,calc(100vw - 36px));margin:auto;color:#263b36;box-shadow:0 18px 60px #12352b30}.discard-dialog::backdrop{background:#18392c66}h2{font-size:20px}p{font-size:13px;color:var(--muted);line-height:1.9;margin:16px 0 24px}.discard-dialog>div{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}
</style>
