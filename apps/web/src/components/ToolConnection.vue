<script setup lang="ts">
import { ref } from 'vue'
import { useTravelApi, type Schema } from '../api'
const api=useTravelApi()

const status=ref<Schema<'ToolServiceStatus'>|null>(null)
const checking=ref(false), error=ref('')
async function check() {
  checking.value=true;error.value=''
  try {status.value=await api.checkToolService()}
  catch(value) {status.value=null;error.value=value instanceof Error?value.message:'连接检查失败'}
  finally {checking.value=false}
}
</script>

<template>
  <section class="tool-connection" aria-label="数据工具连接">
    <h3>数据工具连接</h3>
    <p>检查后端工具服务是否可用。此操作不查询地点和路线。</p>
    <button class="secondary" :disabled="checking" @click="check">{{checking?'正在检查…':'检查工具连接'}}</button>
    <div v-if="status" class="tool-check-result" role="status">
      <p>{{status.mcp_state==='available'?(status.transport==='mcp'?'工具协议检查通过':'后端工具检查通过'):'工具服务暂不可用'}}</p>
      <p>当前调用方式：{{status.transport==='mcp'?'MCP 工具服务':'后端直接查询'}}</p>
      <p>{{status.provider_configured?'地图数据授权已配置；实际查询仍受权限和配额限制。':'地图数据授权待配置；工具连接通过不代表可查询真实数据。'}}</p>
      <small>检查时间：{{status.checked_at?new Date(status.checked_at).toLocaleString('zh-CN'):'未提供'}}</small>
      <p v-if="status.error" class="tool-check-error">{{status.error.message}}</p>
    </div>
    <p v-if="error" role="alert" class="tool-check-error">{{error}}</p>
  </section>
</template>

<style scoped>
.tool-connection{border-top:1px solid var(--line,#e3e8e2);margin-top:20px;padding-top:12px}
.tool-connection p{font-size:12px;line-height:1.7}
.tool-check-result{margin-top:12px;overflow-wrap:anywhere}
.tool-check-result small{color:var(--muted,#66746a)}
.tool-check-error{color:#a24e32}
</style>
