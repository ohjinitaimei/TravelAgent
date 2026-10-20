import { test, expect, type Page } from '@playwright/test'

// Explicit TEST ONLY service. No production provider, external SDK or live credentials.
test.setTimeout(90_000)
const pause=(ms:number)=>new Promise(resolve=>setTimeout(resolve,ms))
test.beforeEach(async({page})=>{
  await page.route(/https:\/\//,route=>route.abort())
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'这次，去哪里？'})).toBeVisible()
})
async function fillPlan(page:Page,maximum=false) {
  const form=page.locator('.planner-form')
  await form.getByLabel('目的地',{exact:true}).fill('TEST ONLY 测试城市')
  await form.getByLabel('地点关键词',{exact:false}).fill(maximum?'TEST ONLY maximum':'TEST ONLY slow')
  await form.getByLabel('出发日期',{exact:true}).fill('2026-10-20')
  await form.getByLabel('旅行天数').selectOption(maximum?'3':'1')
  await form.getByLabel('每天站数').selectOption(maximum?'4':'2')
}
async function task(page:Page) {
  const id=(await page.locator('.task-id').innerText()).replace(/^任务\s+/,'').split(' · ')[0].trim()
  const response=await page.request.get(`/api/v1/travel/tasks/${id}`)
  expect(response.ok()).toBeTruthy();return response.json()
}
async function trip(page:Page,id:string) {
  const response=await page.request.get(`/api/v1/travel/itineraries/${id}`)
  expect(response.ok()).toBeTruthy();return response.json()
}
function countWrites(page:Page) {
  const writes:{url:string;key:string|undefined}[]=[]
  page.on('request',r=>{if(r.method()==='POST'&&/\/travel\/(tasks$|itineraries\/[^/]+\/adjust$)/.test(r.url()))writes.push({url:r.url(),key:r.headers()['idempotency-key']})})
  return writes
}
async function blockStream(page:Page) {await page.route('**/events/stream?*',route=>route.abort())}

test('intermittent read failures recover events and preserve one accepted task',async({page})=>{
  await fillPlan(page);await blockStream(page)
  const writes=countWrites(page)
  let reads=0,eventReads=0
  await page.route(/\/tasks\/[^/?]+$/,async route=>{
    if(route.request().method()!=='GET')return route.continue()
    await pause(250);reads++
    if(reads===1||reads===3)return route.abort('failed')
    return route.continue()
  })
  await page.route(/\/tasks\/[^/]+\/events\?/,async route=>{
    await pause(250);eventReads++
    if(eventReads===1)return route.abort('failed')
    return route.continue()
  })
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const accepted=await task(page)
  expect(accepted.status).toBe('succeeded');expect(reads).toBeGreaterThanOrEqual(4)
  const response=await page.request.get(`/api/v1/travel/tasks/${accepted.id}/events?after=0`)
  const committed=await response.json()
  await expect(page.locator('.event-list li')).toHaveCount(committed.items.length)
  expect(writes).toHaveLength(1);expect(writes[0].key).toBeTruthy()
})

test('sustained outage exhausts bounded retries then resumes the same task',async({page})=>{
  await fillPlan(page);await blockStream(page)
  const writes=countWrites(page)
  let outage=true,reads=0
  await page.route(/\/tasks\/[^/?]+$/,async route=>{
    if(route.request().method()!=='GET')return route.continue()
    if(outage){reads++;await pause(200);return route.abort('failed')}
    return route.continue()
  })
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  const restore=page.getByRole('button',{name:'恢复连接',exact:true})
  await expect.poll(()=>reads).toBe(5)
  await expect(restore).toBeEnabled()
  const accepted=await task(page)
  expect(writes).toHaveLength(1)
  // No polling loop remains after the retry budget is exhausted.
  await pause(700);expect(reads).toBe(5)
  outage=false
  await restore.click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  expect((await task(page)).id).toBe(accepted.id);expect(writes).toHaveLength(1)
})

test('failed final result read keeps the old version explicit and recovers without resubmission',async({page})=>{
  await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
  await page.locator('.saved-card').filter({hasText:'2026-10-10'}).filter({hasText:'SAVED ITINERARY'}).click()
  await expect(page.locator('.timeline')).toContainText('TEST ONLY fixture-a')
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  await page.locator('.edit-day:visible').getByLabel('用户录入费用').first().fill('20.5')
  let unavailable=true,reads=0
  const writes=countWrites(page)
  await page.route(/\/itineraries\/[^/?]+$/,async route=>{
    if(route.request().method()==='GET'&&unavailable){reads++;return route.abort('failed')}
    return route.continue()
  })
  await page.getByRole('button',{name:'保存并重算',exact:true}).click()
  await expect.poll(()=>reads).toBeGreaterThan(0)
  await expect(page.getByRole('button',{name:'恢复连接',exact:true})).toBeEnabled()
  const accepted=await task(page)
  expect(accepted.status).toBe('succeeded')
  await expect(page.getByRole('status',{name:'结果同步'})).toContainText('结果尚未同步')
  await expect(page.locator('.saved-version-note')).toBeVisible()
  await expect(page.getByRole('button',{name:'保存并重算',exact:true})).toBeDisabled()
  unavailable=false
  await page.evaluate(()=>window.dispatchEvent(new Event('online')))
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  await expect(page.getByRole('status',{name:'结果同步'})).toHaveCount(0)
  const saved=await trip(page,accepted.itinerary_id)
  expect(saved.days[0].stops[0].user_cost).toBe(20.5)
  expect(saved.parent_id).toBeTruthy()
  expect((await trip(page,saved.parent_id)).days[0].stops[0].user_cost).toBeNull()
  expect((await task(page)).id).toBe(accepted.id);expect(writes).toHaveLength(1)
})

test('cancellation survives a late in-flight status response',async({page})=>{
  await fillPlan(page);await blockStream(page)
  const writes=countWrites(page)
  let inFlight=false,delivered=false,cancels=0
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/cancel'))cancels++})
  await page.route(/\/tasks\/[^/?]+$/,async route=>{
    if(route.request().method()!=='GET')return route.continue()
    const response=await route.fetch()
    inFlight=true;await pause(2200)
    try {await route.fulfill({response})} catch(e) {
      if(!/cancel|abort|closed/i.test(String(e)))throw e
    } finally {delivered=true}
  })
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect.poll(()=>inFlight).toBeTruthy()
  await page.getByRole('button',{name:'取消任务',exact:true}).click()
  await expect.poll(()=>delivered).toBeTruthy()
  const cancelled=await task(page)
  expect(cancelled.status).toBe('cancelled');expect(cancelled.itinerary_id).toBeNull()
  await expect(page.locator('.execution .status-pill')).toContainText('已取消')
  expect(writes).toHaveLength(1);expect(cancels).toBe(1)
})

test('maximum 12-stop itinerary stays responsive and preserves edits across save and reload',async({page},info)=>{
  await fillPlan(page,true)
  const writes=countWrites(page)
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const initial=await task(page),original=await trip(page,initial.itinerary_id)
  expect(original.optimization.route_queries).toBeLessThanOrEqual(48)
  expect(original.days.map((d:any)=>d.stops.length)).toEqual([4,4,4])
  expect(new Set(original.days.flatMap((d:any)=>d.stops.map((s:any)=>s.poi.id))).size).toBe(12)
  const legs=original.days.flatMap((d:any)=>d.stops.flatMap((s:any)=>s.travel_to_next?[s.travel_to_next]:[]))
  expect(legs).toHaveLength(9);expect(legs.every((leg:any)=>leg.polyline.length===512)).toBeTruthy()
  const samples:{operation:string;ms:number}[]=[]
  async function measure(operation:string,action:()=>Promise<void>) {
    // timeOrigin keeps the clock comparable across page.reload().
    const start=await page.evaluate(()=>performance.timeOrigin+performance.now())
    await action()
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))))
    const elapsed=(await page.evaluate(()=>performance.timeOrigin+performance.now()))-start
    expect(elapsed).toBeGreaterThanOrEqual(0)
    samples.push({operation,ms:elapsed})
  }
  const dayButton=(day:number)=>page.getByRole('button',{name:`DAY ${day+1}`,exact:false})
  const elementsBefore=await page.locator('*').count()
  for(let i=0;i<12;i++)await measure('switch-day',async()=>{
    await dayButton(i%3).click()
    await expect(page.locator('.timeline-stop')).toHaveCount(4)
    await expect(dayButton(i%3)).toHaveAttribute('aria-pressed','true')
  })
  expect(await page.locator('*').count()).toBe(elementsBefore)
  await measure('open-editor',()=>page.getByRole('button',{name:'编辑行程',exact:true}).click())
  await expect(page.locator('.edit-stop')).toHaveCount(12)
  for(let day=0;day<3;day++) {
    await dayButton(day).click()
    await measure('edit-price',()=>page.locator('.edit-day:visible').getByLabel('用户录入费用').first().fill(String(day+0.5)))
  }
  const local=await page.evaluate(()=>Object.entries(localStorage).find(([key])=>key.startsWith('travelagent.edit.v1.'))?.[1])
  expect(local).toBeTruthy();expect(local!.length).toBeLessThan(32768)
  expect(local).not.toContain('polyline');expect(local).not.toContain('longitude')
  await page.getByRole('button',{name:'保存并重算',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const adjusted=await task(page),result=await trip(page,adjusted.itinerary_id)
  expect(result.parent_id).toBe(original.id)
  expect(result.days.map((d:any)=>d.stops[0].user_cost)).toEqual([0.5,1.5,2.5])
  expect((await trip(page,original.id)).days.every((d:any)=>d.stops.every((s:any)=>s.user_cost===null))).toBeTruthy()
  await measure('reload-result',async()=>{
    await page.reload();await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
    await expect(page.locator('.timeline-stop')).toHaveCount(4)
  })
  expect((await task(page)).itinerary_id).toBe(result.id);expect(writes).toHaveLength(2)
  const steady=samples.filter(s=>s.operation==='switch-day'||s.operation==='edit-price').map(s=>s.ms).sort((a,b)=>a-b)
  const p95=steady[Math.ceil(steady.length*.95)-1]
  expect(p95).toBeLessThan(1500);expect(Math.max(...steady)).toBeLessThan(3000)
  expect(samples.find(s=>s.operation==='reload-result')!.ms).toBeLessThan(8000)
  expect(await page.locator('*').count()).toBeLessThan(3000)
  await info.attach('performance.json',{contentType:'application/json',body:JSON.stringify({
    browser:info.project.name,build:'production',network:'local loopback; no SDK or external provider',
    stops:12,days:3,segments:legs.length,points:legs.reduce((n:number,leg:any)=>n+leg.polyline.length,0),
    responseBytes:Buffer.byteLength(JSON.stringify(original)),p95InteractionMs:p95,samples,
  },null,2)})
})
