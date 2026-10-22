<script setup lang="ts">
import type { Poi } from '../api'
import type { PlanForm } from '../schedules'
import AccessibleForm from './AccessibleForm.vue'
import JourneySchedule from './JourneySchedule.vue'
import JourneyEndpoints from './JourneyEndpoints.vue'

defineProps<{form:PlanForm;disabled:boolean;blocked?:boolean;knownPoi:(id?:string|null)=>Poi|null|undefined}>()
const emit=defineEmits<{change:[value:Partial<PlanForm>];loaded:[poi:Poi];submit:[event:SubmitEvent]}>()
function field(key:keyof PlanForm,event:Event){
  const input=event.target as HTMLInputElement
  const numeric=['days','stops_per_day','stay_minutes','budget','max_leg_travel_minutes','max_daily_travel_minutes'].includes(key)
  const value=input.type==='checkbox'?input.checked:numeric?(input.value===''?null:Number(input.value)):input.value
  emit('change',{[key]:value})
}
</script>

<template>
<section class="card planner-form" aria-labelledby="planning-form-title">
          <div class="section-heading"><span class="step">01</span><div><h2 id="planning-form-title" tabindex="-1">这次，去哪里？</h2><p>从几个简单的选择开始</p></div></div>
          <AccessibleForm label="旅行规划" @submit="emit('submit',$event)">
            <fieldset class="planning-group" :disabled="disabled"><legend>目的地与日期</legend>
            <label class="planner-wide">目的地<input :value="form.city" name="city" @input="field('city',$event)" required maxlength="60" placeholder="输入城市，例如杭州" :disabled="disabled"/></label>
            <label class="planner-wide">地点关键词<textarea :value="form.query" name="query" @input="field('query',$event)" required maxlength="240" rows="3" placeholder="例如：博物馆、公园、咖啡" :disabled="disabled"/><small>用于真实地点搜索，硬约束请在下方填写</small></label>
            <label>出发日期<input :value="form.start_date" name="start_date" @input="field('start_date',$event)" type="date" required :disabled="disabled"/></label>
            <div class="field-row"><label>旅行天数<select :value="form.days" name="days" @input="field('days',$event)"><option v-for="n in 3" :value="n">{{n}} 天</option></select></label><label>每天站数<select :value="form.stops_per_day" name="stops_per_day" @input="field('stops_per_day',$event)"><option v-for="n in 4" :value="n">{{n}} 站</option></select></label></div>
            </fieldset>
            <fieldset class="planning-group" :disabled="disabled"><legend>时段与交通</legend>
            <JourneySchedule :value="form" :days="form.days??2" :disabled="disabled" @change="emit('change',$event)"/>
            <label>交通方式<select :value="form.mode" name="mode" @input="field('mode',$event)"><option value="walking">步行 · 真实步行路线</option><option value="driving">驾车 · 真实驾车路线</option></select></label>
            </fieldset>
            <fieldset class="planning-group" :disabled="disabled"><legend>可选约束与起终点</legend>
            <fieldset class="travel-limits"><legend>交通时长偏好（可选）</legend><p class="subtle">按当前{{form.mode==='walking'?'步行':'驾车'}}模式核验，含所选出发和返回；留空只提示负担。</p><label>单段交通上限（分钟）<input :value="form.max_leg_travel_minutes" name="max_leg_travel_minutes" @input="field('max_leg_travel_minutes',$event)" type="number" min="1" max="1439" step="1" placeholder="不限制"/></label><label>每日交通上限（分钟）<input :value="form.max_daily_travel_minutes" name="max_daily_travel_minutes" @input="field('max_daily_travel_minutes',$event)" type="number" min="1" max="1439" step="1" placeholder="不限制"/></label></fieldset>
            <label>总预算（可选）<div class="money-input"><span>¥</span><input :value="form.budget" name="budget" @input="field('budget',$event)" step="any" type="number" min="0" placeholder="输入预算上限"/></div></label>
            <label class="check-label"><input :checked="form.compare_poi_alternatives" name="compare_poi_alternatives" @change="field('compare_poi_alternatives',$event)" type="checkbox" :disabled="disabled"/>比较同类备选地点，减少路途</label><small>可在本次真实搜索中比较有限方案；保持站数、时段与交通条件，可能增加路线查询，评分可能降低或缺失，请核对取舍。编辑时保留你选定的地点。</small>
            <JourneyEndpoints class="planner-endpoints" :value="form" :days="form.days??2" :city="form.city" :disabled="disabled" :known-poi="knownPoi" @change="emit('change',$event)" @loaded="emit('loaded',$event)"/>
            </fieldset>
            <slot/>
            <button class="primary full" type="submit" :disabled="disabled||blocked">{{disabled ? '任务处理中…' : '开始规划'}}<span aria-hidden="true">↗</span></button>
          </AccessibleForm>
          <p class="form-footnote">路线与时间由后端算法计算。缺失的费用保留未知。</p>
        </section>
</template>

<style scoped>
.planning-group{border:0;padding:0;margin:0 0 20px;min-width:0;grid-column:1/-1}
.planning-group legend{font-size:12px;color:var(--green);font-weight:600;margin-bottom:14px;padding:0 0 7px;border-bottom:1px solid var(--line);width:100%}
.planning-group:last-of-type{margin-bottom:8px}.planning-group small{display:block;font-size:11px;line-height:1.7;color:var(--muted);margin:8px 0 12px}
</style>
