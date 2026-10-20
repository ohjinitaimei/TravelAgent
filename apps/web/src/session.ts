import type { PlanRequest } from './api'
import type { PendingSubmission } from './submissions'
import { editDraftKey } from './editDraft'

const KEY = 'travelagent.workspace.v1'
function key(ownerId:string) {return ownerId==='local'?KEY:`${KEY}.user.${encodeURIComponent(ownerId)}`}
export type WorkspaceSession = { form?: PlanRequest; taskId?: string; itineraryId?: string; draftId?: string; pendingSubmission?:PendingSubmission; appliedDraft?:{id:string;revision:number} }

/** Persist user inputs, pending submissions and server IDs, never provider datasets or credentials. */
export function readSession(ownerId='local'): WorkspaceSession {
  try { const value = JSON.parse(localStorage.getItem(key(ownerId)) || '{}'); return value && typeof value === 'object' ? value : {} }
  catch { return {} }
}

export function writeSession(value: WorkspaceSession,ownerId='local') {
  try { localStorage.setItem(key(ownerId), JSON.stringify(value)) } catch { /* Private mode/storage quota must not break the workspace. */ }
}

export function clearSession(ownerId:string) {try {localStorage.removeItem(key(ownerId));localStorage.removeItem(editDraftKey(ownerId))} catch {}}

export function restoreForm(defaults: PlanRequest, stored: unknown): PlanRequest {
  if (!stored || typeof stored !== 'object') return defaults
  const value = stored as Record<string, unknown>
  const result = { ...defaults }
  for (const field of ['city', 'query', 'start_date', 'day_start', 'day_end'] as const) {
    if (typeof value[field] === 'string') result[field] = value[field]
  }
  for (const [field, min, max] of [['days',1,3], ['stops_per_day',1,4], ['stay_minutes',10,360]] as const) {
    const number = value[field]
    if (typeof number === 'number' && Number.isInteger(number) && number >= min && number <= max) result[field] = number
  }
  if (value.mode === 'walking' || value.mode === 'driving') result.mode = value.mode
  if (typeof value.budget === 'number' && Number.isFinite(value.budget) && value.budget >= 0) result.budget = value.budget
  return result
}
