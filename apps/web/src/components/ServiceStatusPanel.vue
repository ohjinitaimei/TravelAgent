<script setup lang="ts">
import { computed } from 'vue'
import { intakeStatus, type ServiceSnapshot } from '../serviceStatus'
const props=defineProps<{state:ServiceSnapshot;mapState:'unconfigured'|'loading'|'ready'|'error';mapVisible:boolean}>()
defineEmits<{refresh:[]}>()
const current=computed(()=>props.state.phase==='ready')
const capability=computed(()=>props.state.capability)
const intake=computed(()=>intakeStatus(capability.value,current.value))
const mapLabel=computed(()=>props.mapVisible?({unconfigured:'浏览器地图未配置',loading:'地图组件加载中',ready:'地图组件已加载',error:'地图加载失败'})[props.mapState]:'前往规划或推荐页面查看地图')
</script>

<template>
  <section id="service-status" class="card service-status" aria-label="旅行服务状态" :aria-busy="state.phase==='loading'">
    <div class="section-title"><div><h2>旅行服务状态</h2><p>配置检查只读取当前服务信息。授权、配额及网络是否可用，以实际操作结果为准。</p></div><button type="button" class="secondary" :disabled="state.phase==='loading'" @click="$emit('refresh')">{{state.phase==='loading'?'正在读取服务状态…':'刷新服务状态'}}</button></div>
    <div role="status" aria-label="服务状态读取结果" aria-live="polite" aria-atomic="true">
      <p class="service-freshness">{{state.phase==='ready'?'已连接后端，以下为本次读取的配置。':state.phase==='loading'?'正在读取后端配置。':state.capability?'以下保留上次读取的配置，当前状态待确认。':'尚未读取到后端配置，不能判断是否缺少授权。'}}<span v-if="state.checkedAt"> 上次读取：{{new Date(state.checkedAt).toLocaleString('zh-CN')}}</span></p>
      <p v-if="state.error" class="service-error">{{state.error}}</p>
    </div>
    <div class="service-grid">
      <div><h3>地点与路线</h3><strong>{{!current?'配置状态待确认':capability?.configured?'地图数据授权已配置':'地图数据授权待配置'}}</strong><p>用于搜索地点和计算真实交通。{{current&&!capability?.configured?'请联系服务管理员配置地图数据服务。':'实际查询仍受服务权限和配额限制。'}}</p></div>
      <div><h3>地图展示</h3><strong>{{mapLabel}}</strong><p v-if="current&&capability?.map_proxy_configured===true">地图代理已配置；域名授权与底图连通性需由地图实际加载确认。</p><p v-else-if="capability?.map_proxy_configured===false&&current">地图代理配置不完整，请联系服务管理员。时间轴和地点列表仍可使用。</p><p v-else>地图代理状态待确认。时间轴和地点列表仍可使用。</p><p v-if="mapVisible&&mapState==='error'">可在地图区域显式重试，当前行程会保留。</p></div>
      <div><h3>自然语言需求整理</h3><strong>{{intake.label}}</strong><p>{{intake.detail}}</p><p v-if="current&&capability">服务开关：{{capability.draft_enabled?'已开启':'未开启'}} · 整理组件：{{capability.helloagents_available?'已安装':'未就绪'}} · 模型配置：{{capability.llm_configured?'完整':'待补全'}}</p></div>
      <div><h3>数据工具</h3><strong>{{!current?'调用方式待确认':capability?.tool_transport==='mcp'?'MCP 工具服务':'后端直接查询'}}</strong><p v-if="current&&capability?.tool_transport==='mcp'&&!capability.mcp_available">MCP 组件未就绪，请联系服务管理员。</p><p v-else>可在“预算与约束”的“数据工具连接”中单独检查。连接通过不代表地图授权验证通过。</p></div>
    </div>
  </section>
</template>

<style scoped>
.service-status{margin-bottom:20px;min-width:0}.service-status .section-title{gap:16px;align-items:flex-start}.service-status h2{font-size:17px}.service-status h3{font-size:12px;margin:0 0 10px}.service-status p{font-size:12px;line-height:1.8;margin-top:8px}.service-status strong{font-size:13px;color:var(--green)}.service-freshness{padding:10px 12px;background:#f3f6ef;border-radius:6px}.service-freshness span{display:block}.service-error{color:#943f29}.service-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;margin-top:20px}.service-grid>div{min-width:0;overflow-wrap:anywhere}.service-status button{flex-shrink:0}
@media(max-width:1200px){.service-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:680px){.service-grid{grid-template-columns:1fr}.service-status .section-title{flex-wrap:wrap}}
</style>
