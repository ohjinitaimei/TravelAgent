<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { authApi, apiBase, type Schema } from './api'
import { TravelClient, fetchTransport } from '../../../packages/api-schema/client'
import { workspaceTransport } from './workspaceTransport'
import { clearSession } from './session'
import WorkspaceShell from './components/WorkspaceShell.vue'
import AccessibleForm from './components/AccessibleForm.vue'

const status=ref<Schema<'AuthStatus'>|null>(null), loading=ref(true), busy=ref(false)
const username=ref(''), password=ref(''), error=ref(''), notice=ref('')
const workspace=shallowRef<{api:TravelClient;controller:AbortController;key:number}|null>(null)
const CHANNEL='travelagent.auth.changed'
let generation=0
let operation=0
function closeWorkspace() {workspace.value?.controller.abort();workspace.value=null}
function expire(message='会话已失效，请重新登录。') {
  operation++
  closeWorkspace();status.value={mode:'session',authenticated:false,user:null,setup_required:false};notice.value=message
}
function accept(value:Schema<'AuthStatus'>) {
  closeWorkspace();status.value=value
  if(value.authenticated&&value.user) {
    const controller=new AbortController()
    workspace.value={controller,key:++generation,api:new TravelClient(workspaceTransport(fetchTransport(apiBase),value.user.id,value.csrf_token,controller.signal,()=>expire()))}
  }
}
function broadcast() {try {localStorage.setItem(CHANNEL,crypto.randomUUID())} catch {}}
async function initialize() {
  const current=++operation
  loading.value=true;error.value='';password.value=''
  try {const value=await authApi.authStatus();if(current===operation) accept(value)} catch(value) {error.value=value instanceof Error?value.message:'无法连接服务'}
  finally {loading.value=false}
}
async function login() {
  const current=++operation
  busy.value=true;error.value='';notice.value=''
  try {
    const created=await authApi.login({username:username.value,password:password.value,transport:'cookie'})
    const value=await authApi.authStatus()
    if(current!==operation) return
    if(!value.authenticated) throw new Error('浏览器未保存会话，请检查 Cookie 或 HTTPS 配置')
    if(value.user?.id!==created.user?.id) throw new Error('账号状态已变化，请重新登录')
    accept(value);broadcast()
  } catch(value) {error.value=value instanceof Error?value.message:'登录失败'}
  finally {password.value='';busy.value=false}
}
async function logout() {
  if(!workspace.value||!status.value?.user||busy.value) return
  busy.value=true;error.value=''
  const owner=status.value.user.id
  try {
    await workspace.value.api.logout()
    closeWorkspace();accept({mode:'session',authenticated:false,user:null,setup_required:false});await nextTick();clearSession(owner);broadcast();notice.value='已退出登录'
  } catch(value) {error.value=value instanceof Error?value.message:'退出失败，请重试'}
  finally {busy.value=false}
}
function otherTab(event:StorageEvent) {if(event.key===CHANNEL) expire('账号状态已在其他页面变化，请重新登录。')}
onMounted(()=>{window.addEventListener('storage',otherTab);void initialize()})
onBeforeUnmount(()=>{closeWorkspace();window.removeEventListener('storage',otherTab)})
</script>

<template>
  <template v-if="workspace&&status?.user">
    <div v-if="error" role="alert" class="account-alert">{{error}}</div>
    <WorkspaceShell :key="workspace.key" :api="workspace.api" :user="status.user" :auth-enabled="status.mode==='session'" @logout="logout"/>
  </template>
  <main v-else class="auth-page">
    <section class="auth-card">
      <div class="eyebrow">TRAVELAGENT · YOUR TRAVEL SPACE</div>
      <h1>{{loading?'正在连接旅行空间':'登录旅行空间'}}</h1>
      <p>保存你的规划，在自己的空间继续每一次旅程。</p>
      <p v-if="notice" role="status">{{notice}}</p>
      <p v-if="error" role="alert" class="auth-error">{{error}}</p>
      <p v-if="status?.setup_required">服务尚未配置账号，请联系管理员。</p>
      <AccessibleForm v-if="!loading&&status?.mode==='session'" label="账号登录" @submit="login">
        <label>账号<input v-model="username" autocomplete="username" required minlength="3" maxlength="40" :disabled="busy"/></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" required maxlength="128" :disabled="busy"/></label>
        <button class="primary full" type="submit" :disabled="busy||status.setup_required">{{busy?'正在登录…':'登录'}}</button>
      </AccessibleForm>
      <button v-if="!loading&&(status?.setup_required||error||status?.mode!=='session')" type="button" class="secondary reconnect-account" :disabled="busy" @click="initialize">{{status?.setup_required?'重新检查账号配置':'重新连接'}}</button>
    </section>
  </main>
</template>

<style scoped>
.auth-page{margin:0;width:100%;min-height:100vh;display:grid;place-items:center;padding:32px;background:#f3f5ef}
.auth-card{width:min(100%,440px);padding:40px;border:1px solid #dde5dc;border-radius:18px;background:white;box-shadow:0 16px 48px #183b2810}
.auth-card h1{font-size:28px;line-height:1.4}.auth-card p{font-size:13px;color:#5e7064;line-height:1.8}
.auth-card form{display:grid;gap:18px;margin-top:24px}.auth-error,.account-alert{color:#943f29!important}
.reconnect-account{margin-top:16px}
.account-alert{position:fixed;right:24px;top:64px;z-index:100;background:#fff0e9;padding:16px;border-radius:10px}
@media(max-width:600px){.auth-card{padding:28px}}
</style>
