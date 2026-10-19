import { TravelClient, TravelApiError, type PlanRequest, type Schema } from '../../../packages/api-schema/client'

export type Operation = {kind:'plan';request:PlanRequest}|{kind:'draft';request:Schema<'DraftRequest'>}|{kind:'adjust';itineraryId:string;request:Schema<'EditRequest'>}|{kind:'retry';taskId:string}
export type PendingSubmission = {key:string;operation:Operation}

export function newSubmission(operation:Operation,key=crypto.randomUUID()):PendingSubmission {
  return {key,operation:JSON.parse(JSON.stringify(operation)) as Operation}
}

export function restoreSubmission(value:unknown):PendingSubmission|null {
  if(!value||typeof value!=='object') return null
  const pending=value as PendingSubmission
  if(typeof pending.key!=='string'||!/^[A-Za-z0-9_.:-]{8,128}$/.test(pending.key)||!pending.operation||typeof pending.operation!=='object') return null
  const op=pending.operation
  if(!['plan','draft','adjust','retry'].includes(op.kind)) return null
  if(op.kind==='retry') {if(typeof op.taskId!=='string'||!op.taskId) return null}
  else {if(!op.request||typeof op.request!=='object'||Array.isArray(op.request)) return null}
  if(op.kind==='adjust'&&(typeof op.itineraryId!=='string'||!op.itineraryId)) return null
  if(JSON.stringify(pending).length>20000) return null
  return {key:pending.key,operation:op}
}

export function sendSubmission(api:TravelClient,pending:PendingSubmission) {
  const op=pending.operation,options={idempotencyKey:pending.key}
  if(op.kind==='plan') return api.create(op.request,options)
  if(op.kind==='draft') return api.createDraft(op.request,options)
  if(op.kind==='adjust') return api.adjust(op.itineraryId,op.request,options)
  return api.retry(op.taskId,options)
}

export async function recoverSubmission(api:TravelClient,pending:PendingSubmission,lookupOnly=false) {
  try {return await api.submission(pending.key)}
  catch(error) {
    if(!(error instanceof TravelApiError&&error.code==='submission_not_found')) throw error
    return lookupOnly?null:sendSubmission(api,pending)
  }
}
