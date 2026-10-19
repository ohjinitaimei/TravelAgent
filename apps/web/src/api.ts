import { TravelClient, fetchTransport } from '../../../packages/api-schema/client'
import { inject, type InjectionKey } from 'vue'
export const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1/travel'
export const authApi = new TravelClient(fetchTransport(apiBase))
export const apiKey:InjectionKey<TravelClient>=Symbol('travel-workspace-api')
export function useTravelApi() {
  const api=inject(apiKey)
  if(!api) throw new Error('Workspace API is unavailable')
  return api
}
export type { Draft, PlanRequest, Task, TravelEvent, Itinerary, Poi, Schema } from '../../../packages/api-schema/client'
