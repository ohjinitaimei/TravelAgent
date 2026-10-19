import { TravelApiError, type Transport } from '../../../packages/api-schema/client'

/** Bind identity/CSRF/abort to a mounted workspace; never read a mutable account. */
export function workspaceTransport(transport:Transport,userId:string,csrf:string|null|undefined,signal:AbortSignal,onExpired:()=>void):Transport {
  return async(path,init={})=>{
    signal.throwIfAborted()
    const combined=init.signal?AbortSignal.any([signal,init.signal]):signal
    try {
      return await transport(path,{...init,signal:combined,headers:{...init.headers,'X-Workspace-User':userId,...(csrf&&init.method&&!['GET','HEAD'].includes(init.method)?{'X-CSRF-Token':csrf}:{})}})
    } catch(error) {
      if(!signal.aborted&&error instanceof TravelApiError&&['authentication_required','workspace_identity_changed','csrf_invalid'].includes(error.code)) onExpired()
      throw error
    }
  }
}
