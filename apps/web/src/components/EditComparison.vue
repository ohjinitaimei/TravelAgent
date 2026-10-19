<script setup lang="ts">
import type { EditChange } from '../editor'
defineProps<{changes:EditChange[]}>()
</script>

<template>
  <section class="edit-comparison" aria-label="本次编辑改动">
    <details :open="changes.length>0">
      <summary>本次编辑改动（{{changes.length}} 项）</summary>
      <p v-if="!changes.length">尚未修改，可直接退出编辑。</p>
      <div v-else class="change-list"><table><caption>与当前已保存版本比较</caption><thead><tr><th>项目</th><th>原值</th><th>编辑后</th></tr></thead><tbody><tr v-for="(change,i) in changes" :key="i"><th scope="row">{{change.label}}</th><td>{{change.before}}</td><td>{{change.after}}</td></tr></tbody></table></div>
    </details>
    <small>保存后重算路线并生成新版本；下方预览不包含尚未重算的交通。</small>
  </section>
</template>

<style scoped>
.edit-comparison{padding:16px 24px;background:#f8faf6;border-bottom:1px solid var(--line);font-size:12px}summary{cursor:pointer;font-weight:600}small,p{display:block;color:var(--muted);line-height:1.8;font-size:11px;margin-top:10px}.change-list{max-height:260px;overflow:auto;margin-top:12px}table{width:100%;border-collapse:collapse;text-align:left;font-size:11px}caption{text-align:left;margin-bottom:8px;color:var(--muted)}th,td{padding:9px 8px;border-top:1px solid var(--line);overflow-wrap:anywhere}tbody th{font-weight:400;max-width:240px}td:last-child{color:var(--green)}
</style>
