import type { PlanRequest, Schema } from './api'

export type ScheduleInput={day_start:string;day_end:string;stay_minutes:string|number|null}
export type ScheduleOptions={day_start?:string;day_end?:string;stay_minutes?:string|number|null;day_schedules?:ScheduleInput[]|null}
export type PlanForm=Omit<PlanRequest,'day_schedules'>&{day_schedules?:ScheduleInput[]|null}
export function scheduleAt(value:ScheduleOptions,index:number):ScheduleInput|undefined {
  return value.day_schedules!=null?value.day_schedules[index]:{
    day_start:value.day_start??'09:00',day_end:value.day_end??'18:00',stay_minutes:value.stay_minutes??60,
  }
}
/** Switching modes must not hide invalid legacy fields that the API still validates. */
export function sharedScheduleReady(value:ScheduleOptions):boolean {
  const clock=(v:unknown):v is string=>typeof v==='string'&&/^([01]\d|2[0-3]):[0-5]\d$/.test(v)
  return clock(value.day_start)&&clock(value.day_end)&&value.day_end>value.day_start&&
    typeof value.stay_minutes==='number'&&Number.isInteger(value.stay_minutes)&&value.stay_minutes>=10&&value.stay_minutes<=360
}
export function cloneSchedules(value:ScheduleInput[]|null|undefined):ScheduleInput[]|null {
  return value?.map(day=>({...day,stay_minutes:day.stay_minutes===''?null:day.stay_minutes}))??null
}
/** Preserve bounded incomplete user inputs for recovery; validate only on submission. */
export function parseScheduleInputs(value:unknown,count:number):ScheduleInput[]|null {
  if(value==null)return null
  if(!Array.isArray(value)||value.length!==count||count<1||count>3)throw Error('逐日时段与天数不一致')
  return value.map(day=>{
    if(!day||typeof day!=='object'||Array.isArray(day)||Object.keys(day).some(key=>!['day_start','day_end','stay_minutes'].includes(key)))throw Error('逐日时段格式无效')
    const clock=(key:string)=>{const v=day[key];if(typeof v!=='string'||v.length>5||v!==''&&!/^([01]\d|2[0-3]):[0-5]\d$/.test(v))throw Error('逐日时段格式无效');return v}
    const v=day.stay_minutes
    if(!(v===null||typeof v==='number'&&Number.isFinite(v)||typeof v==='string'&&v.length<=32))throw Error('逐日停留格式无效')
    return {day_start:clock('day_start'),day_end:clock('day_end'),stay_minutes:v===''?null:v}
  })
}
export function checkedStay(value:unknown):number {
  if(typeof value!=='number'||!Number.isInteger(value)||value<10||value>360)throw Error('默认停留须为 10 至 360 分钟的整数')
  return value
}
export function validatedSchedules(value:ScheduleOptions,count:number):{day_schedules:Schema<'DaySchedule'>[]|null} {
  const daily=parseScheduleInputs(value.day_schedules,count)
  if(daily===null)return {day_schedules:null}
  return {day_schedules:daily.map(day=>{
    if(!day.day_start||!day.day_end||day.day_end<=day.day_start)throw Error('请完整填写逐日时段，结束须晚于开始，不支持跨夜')
    return {day_start:day.day_start,day_end:day.day_end,stay_minutes:checkedStay(day.stay_minutes)}
  })}
}
