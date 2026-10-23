import { test, expect, type Page } from '@playwright/test'

// TEST ONLY browser input/clock checks. External traffic is blocked, and the
// reference-date assertion aborts submission before any model worker is called.
test.beforeEach(async({context})=>{
  await context.route(/https:\/\//,route=>route.abort())
})

async function open(page:Page) {
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'这次，去哪里？'})).toBeVisible()
}

const inputKey='travelagent.requirements.v1.local'
function mutations(page:Page) {
  const writes:string[]=[]
  page.on('request',request=>{
    if(['POST','PATCH'].includes(request.method())&&request.url().includes('/api/v1/travel/'))writes.push(request.url())
  })
  return writes
}
async function backup(page:Page) {
  return page.evaluate(key=>{const value=localStorage.getItem(key);return value?JSON.parse(value):null},inputKey)
}
async function createPartialDraft(page:Page) {
  await page.getByLabel('旅行需求',{exact:true}).fill('TEST ONLY 想逛博物馆，需要预约')
  await page.getByRole('button',{name:'整理为草案'}).click()
  await expect(page.getByRole('heading',{name:'待核对的需求草案'})).toBeVisible()
  const taskId=(await page.locator('.task-id').innerText()).replace(/^任务\s+/,'').split(' · ')[0].trim()
  const task=await(await page.request.get(`/api/v1/travel/tasks/${taskId}`)).json()
  expect(task.kind).toBe('draft');expect(task.itinerary_id).toBeNull()
  return task.draft_id as string
}
async function visitBudgetAndReturn(page:Page) {
  const navigation=page.getByRole('navigation',{name:'工作台导航',exact:true})
  await navigation.getByRole('button',{name:'预算与约束',exact:true}).click()
  await expect(page.getByRole('heading',{name:'看清预算，也看清未知'})).toBeVisible()
  await navigation.getByRole('button',{name:'行程工作台',exact:true}).click()
}

test('unsent requirement text survives a budget visit and explicit refresh recovery without submitting a draft',async({page})=>{
  await open(page)
  const text='TEST ONLY 还未提交的旅行需求：第一天下午出发，想逛博物馆。'
  const writes=mutations(page)
  await page.getByLabel('旅行需求',{exact:true}).fill(text)
  await visitBudgetAndReturn(page)
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(text)
  await expect.poll(async()=>(await backup(page))?.input.text).toBe(text)
  await page.reload()
  const recovery=page.getByRole('region',{name:'本机需求输入',exact:true})
  await expect(recovery).toBeVisible()
  await expect(page.getByLabel('旅行需求',{exact:true})).toBeDisabled()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue('')
  await recovery.getByRole('button',{name:'恢复需求输入',exact:true}).click()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(text)
  await expect(page.getByLabel('旅行需求',{exact:true})).toBeEnabled()
  expect(writes).toEqual([])
})

test('draft submission uses the current reference date after an open page crosses midnight',async({page})=>{
  await page.clock.setFixedTime(new Date('2026-10-24T03:00:00Z'))
  await open(page)
  await page.getByLabel('旅行需求',{exact:true}).fill('TEST ONLY 明天去杭州逛博物馆')
  await page.clock.setFixedTime(new Date('2026-10-25T03:00:00Z'))
  let body:any
  await page.route('**/api/v1/travel/drafts',route=>{
    body=route.request().postDataJSON()
    return route.abort('failed')
  })
  const request=page.waitForRequest(value=>value.method()==='POST'&&value.url().endsWith('/api/v1/travel/drafts'))
  await page.getByRole('button',{name:'整理为草案',exact:false}).click()
  await request
  expect(body.text).toBe('TEST ONLY 明天去杭州逛博物馆')
  expect(body.reference_date).toBe('2026-10-25')
})

test('unsaved clarification preserves zero budget and partial daily blanks across tabs and explicit refresh recovery',async({page},testInfo)=>{
  await open(page)
  const draftId=await createPartialDraft(page),writes=mutations(page)
  const raw='TEST ONLY 仍在编辑的原文，补充暂不提交'
  await page.getByLabel('旅行需求',{exact:true}).fill(raw)
  await page.getByLabel('草案目的地',{exact:true}).fill('TEST ONLY 待保存城市')
  await page.getByLabel('草案预算上限',{exact:true}).fill('0')
  await page.getByLabel('草案天数',{exact:true}).fill('2')
  await page.getByRole('button',{name:'按草案天数创建空白逐日项',exact:true}).click()
  await page.getByLabel('草案第 1 天开始',{exact:true}).fill('14:00')
  await page.getByLabel('草案第 2 天结束',{exact:true}).fill('16:00')
  await visitBudgetAndReturn(page)
  await expect(page.getByLabel('草案目的地',{exact:true})).toHaveValue('TEST ONLY 待保存城市')
  await expect(page.getByLabel('草案预算上限',{exact:true})).toHaveValue('0')
  await expect.poll(async()=>(await backup(page))?.input.clarification.schedulePatch.days['1'].day_end).toBe('16:00')
  const stored=await backup(page)
  expect(stored.input.clarification.sourceId).toBe(draftId)
  expect(stored.input.clarification.sourceRevision).toBe(1)
  expect(stored.input.clarification.answers).toEqual({city:'TEST ONLY 待保存城市',budget:'0',days:'2'})
  expect(stored.input.clarification.schedulePatch).toEqual({count:2,days:{'0':{day_start:'14:00'},'1':{day_end:'16:00'}}})
  expect(Object.keys(stored).sort()).toEqual(['input','updatedAt','version'])
  expect(JSON.stringify(stored)).not.toMatch(/"(?:proposal|evidence|field_sources|confirmed_fields|pois|questions)"/)
  await page.reload()
  const recovery=page.getByRole('region',{name:'本机需求输入',exact:true})
  await expect(recovery).toBeVisible()
  await expect(page.getByLabel('草案目的地',{exact:true})).toBeDisabled()
  await recovery.getByRole('button',{name:'恢复需求输入',exact:true}).click()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(raw)
  await expect(page.getByLabel('草案目的地',{exact:true})).toHaveValue('TEST ONLY 待保存城市')
  await expect(page.getByLabel('草案预算上限',{exact:true})).toHaveValue('0')
  for(const label of ['保存目的地','保存预算上限','保存天数','保存逐日时段与默认停留'])await expect(page.getByLabel(label,{exact:true})).toBeChecked()
  await expect(page.getByLabel('草案第 1 天开始',{exact:true})).toHaveValue('14:00')
  await expect(page.getByLabel('草案第 2 天结束',{exact:true})).toHaveValue('16:00')
  for(const label of ['草案第 1 天结束','草案第 2 天开始','草案第 1 天默认停留（分钟）','草案第 2 天默认停留（分钟）'])await expect(page.getByLabel(label,{exact:true})).toHaveValue('')
  const unchanged=await(await page.request.get(`/api/v1/travel/drafts/${draftId}`)).json()
  expect(unchanged.revision).toBe(1)
  expect(unchanged.proposal.values.city).toBeNull()
  expect(unchanged.proposal.values.day_schedules).toBeNull()
  expect(writes).toEqual([])
  const screenshot=testInfo.outputPath('requirements-partial-recovery-test-only.png')
  await page.locator('.request-assistant').screenshot({path:screenshot})
  await testInfo.attach('Explicit requirement recovery · TEST ONLY data',{path:screenshot,contentType:'image/png'})
})

test('a changed server revision keeps old unsaved clarification read-only until explicitly discarded',async({page})=>{
  await open(page)
  const draftId=await createPartialDraft(page),writes=mutations(page)
  const raw='TEST ONLY 来源变化后仍保留的原文'
  await page.getByLabel('旅行需求',{exact:true}).fill(raw)
  await page.getByLabel('草案目的地',{exact:true}).fill('TEST ONLY 旧版未保存城市')
  await expect.poll(async()=>(await backup(page))?.input.clarification.answers.city).toBe('TEST ONLY 旧版未保存城市')
  // TEST ONLY second client changes the actual server revision; the browser must
  // neither overwrite that newer source nor silently rebase its unsaved patch.
  const updated=await page.request.patch(`/api/v1/travel/drafts/${draftId}`,{data:{expected_revision:1,values:{city:'TEST ONLY 服务器新城市'}}})
  expect(updated.ok()).toBeTruthy();expect((await updated.json()).revision).toBe(2)
  await page.reload()
  await page.getByRole('region',{name:'本机需求输入',exact:true}).getByRole('button',{name:'恢复需求输入',exact:true}).click()
  const conflict=page.getByRole('region',{name:'需求补充来源变化',exact:true})
  await expect(conflict).toBeVisible()
  await expect(page.locator('.requirement-source-conflict')).toContainText('第 1 版')
  await expect(page.locator('.requirement-source-conflict')).toContainText('TEST ONLY 旧版未保存城市')
  await expect(page.locator('.draft-review .status-pill')).toContainText('第 2 版')
  await expect(page.getByRole('button',{name:'保存补充与确认'})).toBeDisabled()
  await expect(page.getByLabel('草案目的地',{exact:true})).toBeDisabled()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(raw)
  expect((await backup(page)).input.clarification.sourceRevision).toBe(1)
  await conflict.getByRole('button',{name:'放弃未保存补充',exact:true}).click()
  await expect(conflict).toHaveCount(0)
  await expect(page.getByLabel('草案目的地',{exact:true})).toHaveValue('TEST ONLY 服务器新城市')
  await expect(page.getByLabel('草案目的地',{exact:true})).toBeEnabled()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(raw)
  await expect.poll(async()=>(await backup(page))?.input.clarification).toBeNull()
  const unchanged=await(await page.request.get(`/api/v1/travel/drafts/${draftId}`)).json()
  expect(unchanged.revision).toBe(2);expect(unchanged.proposal.values.city).toBe('TEST ONLY 服务器新城市')
  expect(writes).toEqual([])
})

test('requirement storage quota failure keeps current input and manual form available without submitting',async({page})=>{
  await open(page)
  const writes=mutations(page)
  // TEST ONLY failure is limited to the requirement backup key. Workspace,
  // authentication and other application storage keep their real behavior.
  await page.evaluate(()=>{
    const original=Storage.prototype.setItem
    Storage.prototype.setItem=function(key:string,value:string){
      if(key.startsWith('travelagent.requirements.v1.'))throw new DOMException('TEST ONLY requirement quota','QuotaExceededError')
      return original.call(this,key,value)
    }
  })
  const raw='TEST ONLY 本机空间不足仍可编辑'
  await page.getByLabel('旅行需求',{exact:true}).fill(raw)
  await expect(page.getByRole('region',{name:'本机需求输入',exact:true})).toContainText('需求输入未能保存到本机')
  await visitBudgetAndReturn(page)
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(raw)
  await expect(page.getByRole('button',{name:'整理为草案'})).toBeEnabled()
  const form=page.getByRole('form',{name:'旅行规划',exact:true})
  await form.getByLabel('目的地',{exact:true}).fill('TEST ONLY 手动表单仍可填写')
  await expect(form.getByLabel('目的地',{exact:true})).toHaveValue('TEST ONLY 手动表单仍可填写')
  expect(await backup(page)).toBeNull()
  expect(writes).toEqual([])
})

test('another page cannot silently overwrite requirement input and latest backup needs explicit recovery',async({page,context})=>{
  await open(page)
  const writes=mutations(page),rawA='TEST ONLY 第一页保留原文',rawB='TEST ONLY 第二页更新原文'
  await page.getByLabel('旅行需求',{exact:true}).fill(rawA)
  await expect.poll(async()=>(await backup(page))?.input.text).toBe(rawA)
  const other=await context.newPage(),otherWrites=mutations(other)
  await open(other)
  await other.getByRole('region',{name:'本机需求输入',exact:true}).getByRole('button',{name:'恢复需求输入',exact:true}).click()
  await other.getByLabel('旅行需求',{exact:true}).fill(rawB)
  await expect.poll(async()=>(await backup(other))?.input.text).toBe(rawB)
  const conflict=page.getByRole('region',{name:'本机需求输入',exact:true})
  await expect(conflict).toContainText('其他页面')
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(rawA)
  await expect(page.getByLabel('旅行需求',{exact:true})).toBeDisabled()
  await conflict.getByRole('button',{name:'读取最新需求备份',exact:true}).click()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(rawA)
  await expect(page.getByLabel('旅行需求',{exact:true})).toBeDisabled()
  await conflict.getByRole('button',{name:'恢复需求输入',exact:true}).click()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue(rawB)
  await expect(page.getByLabel('旅行需求',{exact:true})).toBeEnabled()
  expect((await backup(page)).input.text).toBe(rawB)
  expect(writes).toEqual([]);expect(otherWrites).toEqual([])
  await other.close()
})

test('saving selected budget retains unchecked city and partial daily input until their own explicit submission',async({page})=>{
  await open(page)
  const draftId=await createPartialDraft(page),patches:any[]=[],writes=mutations(page)
  page.on('request',request=>{
    if(request.method()==='PATCH'&&request.url().endsWith(`/drafts/${draftId}`))patches.push(request.postDataJSON())
  })
  const city='TEST ONLY 尚未提交的城市'
  await page.getByLabel('草案目的地',{exact:true}).fill(city)
  await page.getByLabel('保存目的地',{exact:true}).uncheck()
  await page.getByLabel('草案预算上限',{exact:true}).fill('0')
  await page.getByRole('button',{name:'按草案天数创建空白逐日项',exact:true}).click()
  await page.getByLabel('草案第 1 天开始',{exact:true}).fill('14:00')
  await page.getByLabel('保存逐日时段与默认停留',{exact:true}).uncheck()
  await page.getByRole('button',{name:'保存补充与确认'}).click()
  await expect(page.locator('.draft-review .status-pill')).toContainText('第 2 版')
  expect(patches).toEqual([{expected_revision:1,values:{budget:0},confirm_fields:['budget']}])
  const budgetOnly=await(await page.request.get(`/api/v1/travel/drafts/${draftId}`)).json()
  expect(budgetOnly.proposal.values.budget).toBe(0)
  expect(budgetOnly.proposal.values.city).toBeNull()
  expect(budgetOnly.proposal.values.day_schedules).toBeNull()
  await expect(page.getByLabel('草案目的地',{exact:true})).toHaveValue(city)
  await expect(page.getByLabel('保存目的地',{exact:true})).not.toBeChecked()
  await expect(page.getByLabel('草案第 1 天开始',{exact:true})).toHaveValue('14:00')
  await expect(page.getByLabel('草案第 1 天结束',{exact:true})).toHaveValue('')
  await expect(page.getByLabel('草案第 1 天默认停留（分钟）',{exact:true})).toHaveValue('')
  await expect(page.getByLabel('保存逐日时段与默认停留',{exact:true})).not.toBeChecked()
  await expect.poll(async()=>(await backup(page))?.input.clarification.sourceRevision).toBe(2)
  const retained=(await backup(page)).input.clarification
  expect(retained.answers).toEqual({city})
  expect(retained.schedulePatch).toEqual({count:1,days:{'0':{day_start:'14:00'}}})
  expect(retained.selected).not.toHaveProperty('budget')
  await page.reload()
  await page.getByRole('region',{name:'本机需求输入',exact:true}).getByRole('button',{name:'恢复需求输入',exact:true}).click()
  await expect(page.getByLabel('草案目的地',{exact:true})).toHaveValue(city)
  await expect(page.getByLabel('草案第 1 天开始',{exact:true})).toHaveValue('14:00')
  await expect(page.getByLabel('保存目的地',{exact:true})).not.toBeChecked()
  await expect(page.getByLabel('保存逐日时段与默认停留',{exact:true})).not.toBeChecked()
  expect(patches).toHaveLength(1)
  await page.getByLabel('保存目的地',{exact:true}).check()
  await page.getByLabel('保存逐日时段与默认停留',{exact:true}).check()
  await page.getByRole('button',{name:'保存补充与确认'}).click()
  await expect(page.locator('.draft-review .status-pill')).toContainText('第 3 版')
  expect(patches).toHaveLength(2)
  expect(patches[1]).toEqual({expected_revision:2,values:{city,day_schedules:[{day_start:'14:00',day_end:null,stay_minutes:null}]},confirm_fields:['city','day_schedules']})
  const confirmed=await(await page.request.get(`/api/v1/travel/drafts/${draftId}`)).json()
  expect(confirmed.proposal.values.city).toBe(city)
  expect(confirmed.proposal.values.budget).toBe(0)
  expect(confirmed.proposal.values.day_schedules).toEqual([{day_start:'14:00',day_end:null,stay_minutes:null}])
  await expect.poll(()=>backup(page)).toBeNull()
  expect(writes).toHaveLength(2)
})
