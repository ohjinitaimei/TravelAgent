import { TravelClient, fetchTransport } from '../../../packages/api-schema/client'
export const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1/travel'
export const api = new TravelClient(fetchTransport(apiBase))
export type { Draft, PlanRequest, Task, TravelEvent, Itinerary, Poi, Schema } from '../../../packages/api-schema/client'
