import type { Schema } from './api'

export type ServiceSnapshot = {
  phase:'idle'|'loading'|'ready'|'error'|'stale'
  capability:Schema<'Capabilities'>|null
  checkedAt:string|null
  error:string
}
export const initialServiceSnapshot=():ServiceSnapshot=>({phase:'idle',capability:null,checkedAt:null,error:''})

/** A read-only snapshot; failed refreshes never turn old configuration into current proof. */
export class ServiceMonitor {
  state=initialServiceSnapshot()
  private revision=0
  private disposed=false
  private inflight:Promise<void>|null=null
  constructor(private load:()=>Promise<Schema<'Capabilities'>>,private changed:(value:ServiceSnapshot)=>void,private now=()=>new Date().toISOString()) {}
  private update(value:ServiceSnapshot){this.state=value;this.changed(value)}
  refresh():Promise<void> {
    if(this.disposed)return Promise.resolve()
    if(this.inflight)return this.inflight
    const revision=++this.revision
    this.update({...this.state,phase:'loading',error:''})
    const work=Promise.resolve().then(()=>this.load()).then(capability=>{
      if(!this.disposed&&revision===this.revision)this.update({phase:'ready',capability,checkedAt:this.now(),error:''})
    }).catch(()=>{
      if(!this.disposed&&revision===this.revision)this.update({...this.state,phase:this.state.capability?'stale':'error',error:'无法读取服务状态，请检查连接后重试。'})
    }).finally(()=>{if(this.inflight===work)this.inflight=null})
    this.inflight=work
    return work
  }
  offline() {
    if(this.disposed)return
    this.revision++;this.inflight=null
    this.update({...this.state,phase:this.state.capability?'stale':'error',error:'网络已断开，恢复后请刷新服务状态。'})
  }
  dispose(){this.disposed=true;this.revision++;this.inflight=null}
}

export function intakeStatus(capability:Schema<'Capabilities'>|null,current:boolean) {
  if(!capability||!current)return {enabled:false,label:'需求整理状态待确认',detail:'请刷新服务状态后再整理需求，也可直接填写规划表单。'}
  if(!capability.draft_enabled)return {enabled:false,label:'需求整理未启用',detail:'当前服务未开启自然语言整理，可直接填写规划表单。'}
  if(!capability.helloagents_available)return {enabled:false,label:'需求整理依赖未就绪',detail:'请联系服务管理员检查需求整理组件，当前可直接填写规划表单。'}
  if(!capability.llm_configured)return {enabled:false,label:'模型服务配置不完整',detail:'请联系服务管理员配置模型服务，当前可直接填写规划表单。'}
  return {enabled:true,label:'需求整理已配置',detail:'可整理用户表达；实际调用仍受模型服务权限、配额和网络限制。'}
}

export function serviceSummary(state:ServiceSnapshot) {
  if(state.phase==='idle'||state.phase==='loading')return '正在读取服务状态'
  if(state.phase==='stale')return '服务状态需刷新'
  if(state.phase==='error')return '服务状态未读取'
  return state.capability?.configured?'地图数据授权已配置':'地图数据授权待配置'
}
