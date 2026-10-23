import { test, expect, type Page } from '@playwright/test'
import type { Schema } from '../../apps/web/src/api'

// TEST ONLY capability/read-failure injections. Actual data providers and SDK
// requests are never called by these service-status interactions.
const base:Schema<'Capabilities'>={provider:'amap',configured:false,map_proxy_configured:false,
  transport_modes:['walking','driving'],agent:'deterministic_existing_algorithms',
  mcp_connected:false,mcp_available:true,tool_transport:'direct',
  helloagents_available:true,draft_enabled:false,llm_configured:false,
  limitations:['TEST ONLY service status fixture; no external API requests']}

test.beforeEach(async({context})=>{
  await context.route(/https:\/\//,route=>route.abort())
})
async function showServices(page:Page) {
  const panel=page.getByRole('region',{name:'旅行服务状态',exact:true})
  if(!await panel.isVisible())await page.getByRole('button',{name:'服务状态',exact:true}).click()
  await expect(panel).toBeVisible()
  return panel
}
async function formValues(page:Page) {
  const form=page.getByRole('form',{name:'旅行规划',exact:true})
  await form.getByLabel('目的地',{exact:true}).fill('TEST ONLY 保留城市')
  await form.getByLabel('地点关键词',{exact:false}).fill('TEST ONLY 保留需求')
  await form.getByLabel('出发日期',{exact:true}).fill('2026-10-23')
  return form
}
function writes(page:Page) {
  const requests:string[]=[]
  page.on('request',request=>{if(request.method()!=='GET'&&request.url().includes('/api/v1/travel/'))requests.push(request.url())})
  return requests
}

test('initial capability loading is distinct from unconfigured service and does not load a map SDK',async({page})=>{
  let release!:()=>void
  const gate=new Promise<void>(resolve=>{release=resolve})
  let reads=0
  await page.route('**/api/v1/travel/capabilities',async route=>{
    reads++;await gate
    return route.fulfill({json:base})
  })
  const remote:string[]=[]
  page.on('request',request=>{if(request.url().startsWith('https:'))remote.push(request.url())})
  const mutations=writes(page)
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'这次，去哪里？'})).toBeVisible()
  try {
    await expect(page.locator('.sidebar-bottom')).toContainText('正在读取服务状态')
    await expect(page.locator('.sidebar-bottom')).not.toContainText('授权待配置')
    await showServices(page)
  } finally {release()}
  await expect(page.locator('.sidebar-bottom')).toContainText('地图数据授权待配置')
  await expect(page.getByRole('region',{name:'行程地图',exact:true})).toContainText('配置浏览器地图 Key')
  expect(reads).toBe(1)
  expect(remote).toEqual([])
  expect(mutations).toEqual([])
})

test('an unread service state can be retried with one GET without resetting planner inputs or submitting work',async({page})=>{
  let failed=true,reads=0
  await page.route('**/api/v1/travel/capabilities',route=>{
    reads++
    return failed?route.fulfill({status:503,json:{error:{code:'test_only_unavailable',message:'TEST ONLY key=TEST_ONLY_PRIVATE_STATUS_SENTINEL',retryable:true}}})
      :route.fulfill({json:base})
  })
  const mutations=writes(page)
  await page.goto('/')
  await expect(page.locator('.sidebar-bottom')).toContainText('服务状态未读取')
  await expect(page.locator('.sidebar-bottom')).not.toContainText('授权待配置')
  const form=await formValues(page)
  const panel=await showServices(page)
  await expect(panel.getByRole('status',{name:'服务状态读取结果',exact:true})).toContainText('无法读取服务状态，请检查连接后重试。')
  await expect(panel.getByRole('alert')).toHaveCount(0)
  await expect(panel).not.toContainText('TEST_ONLY_PRIVATE_STATUS_SENTINEL')
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('TEST_ONLY_PRIVATE_STATUS_SENTINEL')
  const afterClick:{method:string;url:string}[]=[]
  page.on('request',request=>afterClick.push({method:request.method(),url:request.url()}))
  failed=false
  await panel.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await expect(page.locator('.sidebar-bottom')).toContainText('地图数据授权待配置')
  await expect(form.getByLabel('目的地',{exact:true})).toHaveValue('TEST ONLY 保留城市')
  await expect(form.getByLabel('地点关键词',{exact:false})).toHaveValue('TEST ONLY 保留需求')
  await expect(form.getByLabel('出发日期',{exact:true})).toHaveValue('2026-10-23')
  expect(reads).toBe(2)
  expect(afterClick).toHaveLength(1)
  expect(afterClick[0].method).toBe('GET')
  expect(new URL(afterClick[0].url).pathname).toBe('/api/v1/travel/capabilities')
  expect(mutations).toEqual([])
})

test('a failed refresh marks the last service snapshot stale and recovers without changing saved inputs',async({page})=>{
  let failed=false
  let current={...base,configured:true,map_proxy_configured:true}
  await page.route('**/api/v1/travel/capabilities',route=>failed
    ?route.fulfill({status:503,json:{error:{code:'test_only_status_failure',message:'TEST ONLY 刷新暂不可用',retryable:true}}})
    :route.fulfill({json:current}))
  const mutations=writes(page)
  await page.goto('/')
  await expect(page.locator('.sidebar-bottom')).toContainText('地图数据授权已配置')
  const form=await formValues(page)
  const panel=await showServices(page)
  failed=true
  await panel.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await expect(page.locator('.sidebar-bottom')).toContainText('服务状态需刷新')
  await expect(panel.getByRole('status',{name:'服务状态读取结果',exact:true})).toContainText('无法读取服务状态，请检查连接后重试。')
  await expect(panel.getByRole('alert')).toHaveCount(0)
  await expect(panel).toContainText('上次')
  // Backend proxy credentials do not prove that this no-key browser build has
  // loaded the SDK, and no private credential value is sent to the browser.
  await expect(page.getByRole('region',{name:'行程地图',exact:true})).toContainText('配置浏览器地图 Key')
  await expect(panel).not.toContainText('AMAP_JS_SECURITY_CODE=')
  current={...base,configured:false,map_proxy_configured:false}
  failed=false
  await panel.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await expect(page.locator('.sidebar-bottom')).toContainText('地图数据授权待配置')
  await expect(form.getByLabel('目的地',{exact:true})).toHaveValue('TEST ONLY 保留城市')
  await expect(form.getByLabel('地点关键词',{exact:false})).toHaveValue('TEST ONLY 保留需求')
  expect(mutations).toEqual([])
})

test('optional model states explain disabled intake while manual planning remains available',async({page})=>{
  let current={...base}
  await page.route('**/api/v1/travel/capabilities',route=>route.fulfill({json:current}))
  const mutations=writes(page)
  await page.goto('/')
  await expect(page.locator('.sidebar-bottom')).toContainText('地图数据授权待配置')
  const form=await formValues(page)
  await page.getByLabel('旅行需求',{exact:true}).fill('TEST ONLY 保留自然语言需求')
  const parse=page.getByRole('button',{name:'整理为草案',exact:false})
  const assistant=page.locator('.request-assistant')
  const panel=await showServices(page)
  const modes=[
    {flags:{draft_enabled:false,helloagents_available:true,llm_configured:true},reason:'未启用'},
    {flags:{draft_enabled:true,helloagents_available:false,llm_configured:true},reason:'依赖'},
    {flags:{draft_enabled:true,helloagents_available:true,llm_configured:false},reason:'模型服务配置'},
  ]
  for(const {flags,reason} of modes) {
    current={...base,...flags}
    await panel.getByRole('button',{name:'刷新服务状态',exact:true}).click()
    await expect(assistant).toContainText(reason)
    await expect(parse).toBeDisabled()
    await expect(form.getByLabel('目的地',{exact:true})).toBeEnabled()
    await expect(form.getByRole('button',{name:'开始规划',exact:true})).toBeEnabled()
  }
  current={...base,draft_enabled:true,helloagents_available:true,llm_configured:true}
  await panel.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await expect(parse).toBeEnabled()
  await expect(page.getByLabel('旅行需求',{exact:true})).toHaveValue('TEST ONLY 保留自然语言需求')
  await expect(form.getByLabel('目的地',{exact:true})).toHaveValue('TEST ONLY 保留城市')
  expect(mutations).toEqual([])
})
