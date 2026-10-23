/** Intake uses Asia/Shanghai; new submissions must not reuse a page-open date. */
export function intakeReferenceDate(now=new Date()):string {
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now)
  const part=(type:string)=>parts.find(value=>value.type===type)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}
