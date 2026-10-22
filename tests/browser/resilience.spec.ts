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

async function endpointQueries(page:Page) {
  const poi=(id:string)=>({id,name:`TEST ONLY ${id}`,longitude:116.2,latitude:39.9,source:{provider:'user_input',retrieved_at:'2026-10-22T00:00:00Z',coordinate_system:'GCJ-02'},missing_fields:['city','address','category','rating','average_spend','opening_hours']})
  // Explicit TEST ONLY REST search/detail fixtures. Worker schedules are still produced by the isolated API.
  await page.route(/\/api\/v1\/travel\/pois(?:\?|\/)/,async route=>{
    const url=new URL(route.request().url())
    if(url.pathname.endsWith('/pois')) {
      const keyword=url.searchParams.get('keyword')??''
      if(keyword==='TEST ONLY delayed'){await pause(650);return route.fulfill({json:{items:[poi('old-city-result')]}})}
      return route.fulfill({json:{items:[poi(keyword.includes('return')?'endpoint-return':'endpoint-home')]}})
    }
    return route.fulfill({json:poi(decodeURIComponent(url.pathname.split('/').at(-1)!))})
  })
}
async function chooseEndpoint(page:Page,label:string,keyword:string) {
  const picker=page.getByRole('group',{name:`${label}（可选）`,exact:true}).first()
  await picker.getByLabel(`${label}搜索`,{exact:true}).fill(keyword)
  await picker.getByRole('button',{name:`搜索${label}`,exact:true}).click()
  await picker.getByRole('button',{name:/^选择 TEST ONLY/}).click()
}

test('single-day endpoints survive draft refresh and offline clear while saved totals and source stay accurate',async({page,context})=>{
  await endpointQueries(page);await fillPlan(page)
  await chooseEndpoint(page,'出发地','TEST ONLY home')
  await chooseEndpoint(page,'返回地','TEST ONLY return')
  const writes=countWrites(page)
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const parent=await trip(page,(await task(page)).itinerary_id)
  expect(parent.days[0].stops[0].arrival_time).toBe('09:37')
  expect(parent.days[0].return_arrival_time).toBe('12:51')
  await expect(page.locator('.boundary-stop')).toHaveCount(2)
  await expect(page.getByRole('button',{name:'DAY 1',exact:false})).toContainText('总交通 111 分钟')
  await page.locator('.map-stop-list > summary').click()
  await page.getByRole('button',{name:'地图返回地 TEST ONLY endpoint-return',exact:true}).click()
  await expect(page.getByRole('button',{name:'地图定位返回地 TEST ONLY endpoint-return',exact:true})).toBeFocused()
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  const editor=page.getByRole('form',{name:'行程编辑',exact:true})
  await editor.getByRole('button',{name:'清除返回地',exact:true}).click()
  await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('返回地')
  await expect(page.getByRole('status',{name:'编辑草稿存储'})).toContainText('已保存在本机')
  page.once('dialog',dialog=>dialog.accept());await page.reload()
  await page.getByRole('button',{name:'恢复编辑草稿',exact:true}).click()
  await expect(editor.getByRole('button',{name:'清除返回地',exact:true})).toHaveCount(0)
  await expect(editor.getByRole('button',{name:'清除出发地',exact:true})).toBeVisible()
  try {
    await context.setOffline(true)
    await page.getByRole('button',{name:'保存并重算',exact:true}).click()
    await expect(page.getByRole('button',{name:'恢复上次提交',exact:true})).toBeEnabled()
  } finally {await context.setOffline(false)}
  const response=page.waitForResponse(r=>r.url().endsWith('/adjust')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'恢复上次提交',exact:true}).click()
  const accepted=await(await response).json()
  await expect(page.locator('.task-id')).toContainText(accepted.id)
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const child=await trip(page,(await task(page)).itinerary_id)
  expect(child.request.day_destination_poi_id).toBeNull();expect(child.request.day_origin_poi_id).toBe('endpoint-home')
  expect(child.parent_id).toBe(parent.id);expect(child.days[0].return_arrival_time).toBeNull()
  await expect(page.getByRole('button',{name:'DAY 1',exact:false})).toContainText('总交通 74 分钟')
  expect(await trip(page,parent.id)).toEqual(parent)
  const adjustments=writes.filter(w=>w.url.endsWith('/adjust'))
  expect(adjustments).toHaveLength(2);expect(adjustments[0].key).toBeTruthy();expect(adjustments[0].key).toBe(adjustments[1].key)
  await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
  await page.getByLabel('搜索已保存行程').fill(child.id)
  await page.getByRole('button',{name:'对比来源版本',exact:true}).click()
  const comparison=page.getByRole('region',{name:'已保存版本对照'})
  await expect(comparison.getByRole('row').filter({hasText:'已保存总交通'})).toContainText('111 分钟')
  await expect(comparison.getByRole('row').filter({hasText:'已保存总交通'})).toContainText('74 分钟')
  await expect(comparison.getByRole('row').filter({hasText:'返回地'})).toContainText('未设置')
})

test('shared multiday endpoints reset daily clocks and survive restored edits without altering the source',async({page})=>{
  await endpointQueries(page);await fillPlan(page)
  const form=page.getByRole('form',{name:'旅行规划',exact:true})
  await form.getByLabel('地点关键词',{exact:false}).fill('TEST ONLY shared endpoints')
  await form.getByLabel('旅行天数').selectOption('2')
  await chooseEndpoint(page,'出发地','TEST ONLY home');await chooseEndpoint(page,'返回地','TEST ONLY return')
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const parent=await trip(page,(await task(page)).itinerary_id)
  expect(parent.days).toHaveLength(2)
  for(const day of parent.days){expect(day.origin_departure_time).toBe('09:00');expect(day.origin_poi.id).toBe('endpoint-home');expect(day.destination_poi.id).toBe('endpoint-return')}
  const expected=parent.days.map((d:any)=>d.stops.reduce((sum:number,s:any)=>sum+(s.travel_to_next?.duration_min??0),0)+d.origin_segment.duration_min+d.destination_segment.duration_min)
  for(let i=0;i<2;i++){
    await page.getByRole('button',{name:`DAY ${i+1}`,exact:false}).click()
    await expect(page.locator('.boundary-stop')).toHaveCount(2)
    await expect(page.getByRole('button',{name:`DAY ${i+1}`,exact:false})).toContainText(`总交通 ${expected[i]} 分钟`)
  }
  await expect(page.getByRole('region',{name:'分日与交通对比'})).toContainText('含停留、站间交通及所选起终点往返')
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  const editor=page.getByRole('form',{name:'行程编辑',exact:true})
  await editor.getByRole('button',{name:'清除返回地',exact:true}).click()
  await expect(page.getByRole('status',{name:'编辑草稿存储'})).toContainText('已保存在本机')
  page.once('dialog',dialog=>dialog.accept());await page.reload()
  await page.getByRole('button',{name:'恢复编辑草稿',exact:true}).click()
  await expect(editor.getByRole('button',{name:'清除返回地',exact:true})).toHaveCount(0)
  await expect(editor.getByRole('button',{name:'清除出发地',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'保存并重算',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const child=await trip(page,(await task(page)).itinerary_id)
  expect(child.parent_id).toBe(parent.id)
  for(const day of child.days){expect(day.origin_poi.id).toBe('endpoint-home');expect(day.destination_poi).toBeNull();expect(day.return_arrival_time).toBeNull()}
  expect(await trip(page,parent.id)).toEqual(parent)
  await page.reload();await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'DAY 2',exact:false}).click()
  await expect(page.locator('.boundary-stop')).toHaveCount(1)
})

test('endpoint time diagnostics preserve shared selections and reject stale search results',async({page})=>{
  await endpointQueries(page);await fillPlan(page)
  const form=page.getByRole('form',{name:'旅行规划',exact:true})
  const origin=page.getByRole('group',{name:'出发地（可选）',exact:true}).first()
  await origin.getByLabel('出发地搜索',{exact:true}).fill('TEST ONLY delayed')
  await origin.getByRole('button',{name:'搜索出发地',exact:true}).click()
  await form.getByLabel('目的地',{exact:true}).fill('TEST ONLY changed city')
  await pause(800)
  await expect(origin.getByRole('button',{name:'选择 TEST ONLY old-city-result',exact:true})).toHaveCount(0)
  await chooseEndpoint(page,'出发地','TEST ONLY home');await chooseEndpoint(page,'返回地','TEST ONLY return')
  await form.getByLabel('每日结束',{exact:true}).fill('12:30')
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  const guide=page.getByRole('region',{name:'时间约束调整建议'})
  await expect(guide).toBeVisible()
  const row=guide.getByRole('row').filter({hasText:'第 1 天'})
  await expect(row.getByRole('cell')).toHaveText(['120','37','37','37','231','21'])
  expect((await task(page)).itinerary_id).toBeNull()
  await form.getByRole('button',{name:'清除返回地',exact:true}).click()
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const saved=await trip(page,(await task(page)).itinerary_id)
  expect(saved.days[0].destination_poi).toBeNull()
  expect(saved.days[0].origin_poi.id).toBe('endpoint-home')
})

test('complete user journey repairs constraints, restores a draft and saves one adjusted version after offline recovery',async({page,context},info)=>{
  const writes=countWrites(page)
  const form=page.getByRole('form',{name:'旅行规划',exact:true})
  async function submit(button:string,path:string) {
    const response=page.waitForResponse(r=>r.url().endsWith(path)&&r.request().method()==='POST')
    await page.getByRole('button',{name:button,exact:true}).click()
    const accepted=await(await response).json()
    await expect(page.locator('.task-id')).toContainText(accepted.id)
    return accepted.id as string
  }
  let failed:any,original:any,adjusted:any
  await test.step('repair the failed time window with an explicit new task',async()=>{
    await fillPlan(page)
    await form.getByLabel('出发日期',{exact:true}).fill('2026-10-23')
    await form.getByLabel('每日结束',{exact:true}).fill('09:01')
    await form.getByLabel('总预算（可选）',{exact:false}).fill('300')
    await submit('开始规划','/tasks')
    const guide=page.getByRole('region',{name:'时间约束调整建议'})
    await expect(guide).toBeVisible()
    failed=await task(page)
    expect(failed.status).toBe('failed');expect(failed.itinerary_id).toBeNull()
    expect(failed.retry_available).toBe(false)
    await guide.getByRole('button',{name:'调整每日时段',exact:true}).click()
    await expect(form.getByLabel('每日结束',{exact:true})).toBeFocused()
    await form.getByLabel('每日结束',{exact:true}).fill('18:00')
    const id=await submit('开始规划','/tasks')
    expect(id).not.toBe(failed.id)
    await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
    original=await trip(page,(await task(page)).itinerary_id)
    expect(original.days[0].stops).toHaveLength(2)
    await expect(page.locator('.event-list li').first()).toBeVisible()
  })
  await test.step('keep unknown budget distinct from zero and restore local input after refresh',async()=>{
    await page.getByRole('button',{name:'预算与约束',exact:false}).first().click()
    await expect(page.locator('.budget-stats')).toContainText('总额未知，无法确认预算满足')
    expect(original.budget.total).toBeNull()
    await page.getByRole('button',{name:'行程工作台',exact:false}).first().click()
    await page.getByRole('button',{name:'编辑行程',exact:true}).click()
    await page.getByLabel('停留（分钟）',{exact:true}).first().fill('90')
    await page.getByLabel('用户录入费用',{exact:true}).first().fill('0')
    await expect(page.getByRole('status',{name:'编辑草稿存储'})).toContainText('已保存在本机')
    page.once('dialog',dialog=>dialog.accept())
    await page.reload()
    await expect(page.getByRole('region',{name:'本机编辑草稿'})).toBeVisible()
    await page.getByRole('button',{name:'恢复编辑草稿',exact:true}).click()
    await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('90 分钟')
    await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('0 元')
    expect(writes).toHaveLength(2)
  })
  await test.step('recover the same offline submission and preserve its source version',async()=>{
    try {
      await context.setOffline(true)
      await page.getByRole('button',{name:'保存并重算',exact:true}).click()
      await expect(page.getByRole('button',{name:'恢复上次提交',exact:true})).toBeEnabled()
      await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('90 分钟')
    } finally {await context.setOffline(false)}
    await submit('恢复上次提交','/adjust')
    await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
    adjusted=await trip(page,(await task(page)).itinerary_id)
    expect(adjusted.parent_id).toBe(original.id)
    expect(adjusted.days[0].stops[0].stay_minutes).toBe(90)
    expect(adjusted.days[0].stops[0].user_cost).toBe(0)
    expect(adjusted.budget.total).toBeNull()
    const adjustments=writes.filter(write=>write.url.endsWith('/adjust'))
    expect(adjustments).toHaveLength(2)
    expect(adjustments[0].key).toBeTruthy();expect(adjustments[1].key).toBe(adjustments[0].key)
    expect(await trip(page,original.id)).toEqual(original)
    const oldFailure=await(await page.request.get(`/api/v1/travel/tasks/${failed.id}`)).json()
    expect(oldFailure.error).toEqual(failed.error)
  })
  await test.step('find the saved adjustment, compare facts and reopen its unchanged source',async()=>{
    await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
    await page.getByLabel('搜索已保存行程').fill(adjusted.id)
    await expect(page.locator('.saved-card')).toHaveCount(1)
    await page.getByRole('button',{name:'对比来源版本',exact:true}).click()
    const comparison=page.getByRole('region',{name:'已保存版本对照'})
    await expect(comparison.getByRole('table')).toHaveCount(2)
    const changes=comparison.getByRole('table').nth(1)
    await expect(changes).toContainText('90 分钟');await expect(changes).toContainText('0 元')
    await comparison.getByRole('button',{name:'打开对照中的来源版本',exact:true}).click()
    await expect(page.locator('.workspace-version')).toContainText(original.id.slice(0,8))
    await page.reload()
    await expect(page.locator('.workspace-version')).toContainText(original.id.slice(0,8))
    expect(await trip(page,original.id)).toEqual(original)
    expect(writes).toHaveLength(4)
    const listing=await(await page.request.get(`/api/v1/travel/itineraries?parent_id=${original.id}`)).json()
    expect(listing.total).toBe(1);expect(listing.items[0].id).toBe(adjusted.id)
    await info.attach('complete-journey-test-only',{body:JSON.stringify({fixture:'TEST ONLY',failedTask:failed.id,source:original.id,adjustment:adjusted.id,writeAttempts:writes.length,acceptedTasks:3,sourceUnchanged:true}),contentType:'application/json'})
  })
})

test('draft recovery stays disabled until startup task synchronization is complete',async({page})=>{
  await fillPlan(page)
  await page.getByRole('button',{name:'开始规划',exact:true}).click()
  await expect(page.getByText('行程已生成并保存',{exact:true})).toBeVisible()
  const current=await task(page)
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  await page.getByLabel('停留（分钟）',{exact:true}).first().fill('90')
  await expect(page.getByRole('status',{name:'编辑草稿存储'})).toContainText('已保存在本机')
  let release!:()=>void,reading=false,hold=true
  const gate=new Promise<void>(resolve=>{release=resolve})
  await page.route(`**/tasks/${current.id}`,async route=>{
    if(hold&&route.request().method()==='GET'){reading=true;await gate}
    await route.continue()
  })
  try {
    page.once('dialog',dialog=>dialog.accept());await page.reload()
    await expect.poll(()=>reading).toBeTruthy()
    await expect(page.getByRole('button',{name:'恢复编辑草稿',exact:true})).toBeDisabled()
  } finally {hold=false;release()}
  await page.getByRole('button',{name:'恢复编辑草稿',exact:true}).click()
  await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('90 分钟')
})

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
