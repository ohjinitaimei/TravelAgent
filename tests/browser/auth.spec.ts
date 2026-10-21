import { test, expect, type Page } from '@playwright/test'

const password='TEST ONLY account password 2026'
test.beforeEach(async({page,context})=>{
  await context.route(/https:\/\//,route=>route.abort())
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
})
async function login(page:Page,name='test-alpha') {
  await page.getByLabel('账号',{exact:true}).fill(name)
  await page.getByLabel('密码',{exact:true}).fill(password)
  const response=page.waitForResponse(value=>value.url().endsWith('/api/v1/travel/auth/login')&&value.request().method()==='POST')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.locator('.local-badge')).toHaveText(name)
  return response
}
async function saved(page:Page) {
  await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
  await expect(page.locator('.saved-card').first()).toBeVisible()
}

test('keyboard login validation focuses an error summary without sending invalid credentials',async({page})=>{
  let posts=0
  page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/auth/login'))posts++})
  await page.getByRole('button',{name:'登录',exact:true}).focus();await page.keyboard.press('Enter')
  const summary=page.getByRole('alert',{name:'账号登录错误'})
  await expect(summary).toBeFocused();await expect(summary).toContainText('账号');await expect(summary).toContainText('密码')
  await summary.getByRole('button',{name:/账号/}).focus();await page.keyboard.press('Enter')
  await expect(page.getByLabel('账号',{exact:true})).toBeFocused()
  await page.getByLabel('账号',{exact:true}).fill('   ')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(summary).toContainText('不能只填写空格')
  expect(posts).toBe(0)
})

test('expired session retains an editor draft only for its owner and explicit logout removes it',async({page})=>{
  // Dedicated accounts keep this multi-login scenario independent of the existing rate window.
  await login(page,'test-draft-alpha');await saved(page);await page.locator('.saved-card').first().click()
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  await page.getByLabel('用户录入费用').first().fill('31')
  await expect(page.getByRole('status',{name:'编辑草稿存储'})).toContainText('已保存在本机')
  const status=await (await page.request.get('/api/v1/travel/auth/status')).json()
  expect((await page.request.post('/api/v1/travel/auth/logout',{headers:{'X-CSRF-Token':status.csrf_token}})).ok()).toBeTruthy()
  await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  await login(page,'test-draft-beta')
  await expect(page.getByRole('region',{name:'本机编辑草稿'})).toHaveCount(0)
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await login(page,'test-draft-alpha')
  await page.getByRole('button',{name:'恢复编辑草稿',exact:true}).click()
  await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('31 元')
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await page.getByRole('dialog',{name:'有未保存的行程修改'}).getByRole('button',{name:'放弃修改并退出登录',exact:true}).click()
  await login(page,'test-draft-alpha')
  await expect(page.getByRole('region',{name:'本机编辑草稿'})).toHaveCount(0)
})

test('login, refresh and logout use HttpOnly cookies without exposing tokens',async({page,context,browserName},testInfo)=>{
  await page.screenshot({path:testInfo.outputPath('auth-login-test-only.png'),fullPage:true})
  await page.getByLabel('账号',{exact:true}).fill('test-alpha')
  await page.getByLabel('密码',{exact:true}).fill('TEST ONLY incorrect password')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('账号或密码不正确')
  await expect(page.getByRole('alert',{name:'账号登录错误'})).toHaveCount(0)
  const response=await login(page)
  const setCookie=(await response.headersArray()).find(header=>header.name.toLowerCase()==='set-cookie')?.value??''
  expect(setCookie).toMatch(/(?:^|;\s*)SameSite=Strict(?:;|$)/i)
  const cookie=(await context.cookies()).find(value=>value.name==='travelagent_session')!
  expect(cookie.httpOnly).toBeTruthy()
  if(browserName==='webkit'&&process.platform==='win32') {
    // The pinned engine's own cookie tests mark Windows reporting unsupported.
    testInfo.annotations.push({type:'platform-limitation',description:'Windows WebKit reports SameSite=None; verified server Set-Cookie=Strict. https://github.com/microsoft/playwright/blob/v1.64.1/tests/library/browsercontext-cookies.spec.ts#L110-L120'})
  } else expect(cookie.sameSite).toBe('Strict')
  expect(await page.evaluate(()=>document.cookie)).not.toContain(cookie.value)
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain(cookie.value)
  await saved(page)
  await expect(page.locator('.saved-card')).toHaveCount(1)
  await expect(page.locator('.saved-panel')).toContainText('TEST ONLY alpha')
  await expect(page.locator('.saved-panel')).not.toContainText('TEST ONLY beta')
  await page.reload()
  await expect(page.locator('.local-badge')).toHaveText('test-alpha')
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  expect((await page.request.get('/api/v1/travel/itineraries')).status()).toBe(401)
  expect((await context.cookies()).some(value=>value.name==='travelagent_session')).toBeFalsy()
})

test('logout asks before discarding itinerary edits and canceled logout keeps the same account',async({page})=>{
  await login(page);await saved(page)
  await page.locator('.saved-card').first().click()
  await page.getByRole('button',{name:'编辑行程',exact:true}).click()
  await page.getByLabel('用户录入费用').first().fill('20')
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'有未保存的行程修改'})
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button',{name:'继续编辑',exact:true}).click()
  await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeFocused()
  await expect(page.locator('.local-badge')).toHaveText('test-alpha')
  await expect(page.getByRole('region',{name:'本次编辑改动'})).toContainText('20 元')
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await dialog.getByRole('button',{name:'放弃修改并退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  expect((await page.request.get('/api/v1/travel/itineraries')).status()).toBe(401)
})

test('independent users cannot open or adjust each other saved itineraries',async({page,browser})=>{
  await login(page)
  const own=await (await page.request.get('/api/v1/travel/itineraries')).json()
  const other=await browser.newContext({baseURL:process.env.E2E_BASE_URL})
  try {
    await other.route(/https:\/\//,route=>route.abort())
    const beta=await other.newPage();await beta.goto('/');await login(beta,'test-beta');await saved(beta)
    await expect(beta.locator('.saved-panel')).toContainText('TEST ONLY beta')
    await expect(beta.locator('.saved-panel')).not.toContainText('TEST ONLY alpha')
    expect((await beta.request.get(`/api/v1/travel/itineraries/${own.items[0].id}`)).status()).toBe(404)
    const status=await (await beta.request.get('/api/v1/travel/auth/status')).json()
    const denied=await beta.request.post(`/api/v1/travel/itineraries/${own.items[0].id}/adjust`,{headers:{'X-CSRF-Token':status.csrf_token},data:{poi_ids_by_day:[['fixture-a','fixture-b']]}})
    expect(denied.status()).toBe(404)
  } finally {await other.close()}
})

test('account changes in another tab close the previous workspace',async({page,context})=>{
  await login(page)
  await page.locator('.planner-form').getByLabel('目的地',{exact:true}).fill('TEST ONLY alpha private input')
  const other=await context.newPage();await other.goto('/')
  await expect(other.locator('.local-badge')).toHaveText('test-alpha')
  await other.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  await login(other,'test-beta')
  await expect(page.getByRole('status')).toContainText('账号状态已在其他页面变化')
  await expect(page.locator('.planner-form')).toHaveCount(0)
  await expect(other.locator('.planner-form').getByLabel('目的地',{exact:true})).toHaveValue('')
})

test('revoked session returns to login and restores only the same user form',async({page})=>{
  await login(page)
  await page.locator('.planner-form').getByLabel('目的地',{exact:true}).fill('TEST ONLY alpha recovery')
  const status=await (await page.request.get('/api/v1/travel/auth/status')).json()
  expect((await page.request.post('/api/v1/travel/auth/logout',{headers:{'X-CSRF-Token':status.csrf_token}})).ok()).toBeTruthy()
  await page.getByRole('button',{name:'已保存行程',exact:false}).first().click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  await expect(page.getByRole('status')).toContainText('会话已失效')
  await login(page)
  await page.getByRole('button',{name:'行程工作台',exact:false}).first().click()
  await expect(page.locator('.planner-form').getByLabel('目的地',{exact:true})).toHaveValue('TEST ONLY alpha recovery')
})

test('unconfirmed submission is not carried into a different account after logout',async({page})=>{
  await login(page)
  const form=page.locator('.planner-form')
  await form.getByLabel('目的地',{exact:true}).fill('TEST ONLY alpha private plan')
  await form.getByLabel('地点关键词',{exact:false}).fill('TEST ONLY slow')
  await form.getByLabel('出发日期',{exact:true}).fill('2026-10-20')
  await form.getByLabel('旅行天数').selectOption('1');await form.getByLabel('每天站数').selectOption('2')
  await page.route('**/api/v1/travel/tasks',async route=>{await route.fetch();await route.abort()})
  await page.getByRole('button',{name:'开始规划'}).click()
  await expect(page.getByRole('button',{name:'恢复上次提交'})).toBeEnabled()
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  await page.unroute('**/api/v1/travel/tasks')
  await login(page,'test-beta')
  await expect(page.getByRole('button',{name:'恢复上次提交'})).toHaveCount(0)
  await expect(page.locator('.planner-form').getByLabel('目的地',{exact:true})).toHaveValue('')
  await saved(page)
  await expect(page.locator('.saved-panel')).not.toContainText('TEST ONLY alpha private plan')
})

test('native bearer login stays independent from browser cookies',async({page,context})=>{
  const response=await page.request.post('/api/v1/travel/auth/login',{data:{username:'test-beta',password,transport:'bearer'}})
  expect(response.ok()).toBeTruthy()
  const value=await response.json()
  expect(value.csrf_token).toBeNull()
  const headers={Authorization:`Bearer ${value.access_token}`}
  const own=await (await page.request.get('/api/v1/travel/itineraries',{headers})).json()
  expect(own.items.every((item:{title:string})=>item.title.includes('TEST ONLY beta'))).toBeTruthy()
  expect((await context.cookies()).some(cookie=>cookie.name==='travelagent_session')).toBeFalsy()
  expect((await page.request.post('/api/v1/travel/auth/logout',{headers})).ok()).toBeTruthy()
  expect((await page.request.get('/api/v1/travel/itineraries',{headers})).status()).toBe(401)
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
})

test('offline logout failure preserves account identity until an explicit successful logout',async({page,context})=>{
  await login(page)
  try {
    await context.setOffline(true)
    await page.getByRole('button',{name:'退出登录',exact:true}).click()
    await expect(page.getByRole('alert')).toContainText('无法连接服务')
    await expect(page.locator('.local-badge')).toHaveText('test-alpha')
    await expect(page.getByRole('button',{name:'退出登录',exact:true})).toBeEnabled()
  } finally {await context.setOffline(false)}
  const status=await (await page.request.get('/api/v1/travel/auth/status')).json()
  expect(status.authenticated).toBe(true)
  expect(status.user.username).toBe('test-alpha')
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'登录旅行空间',exact:true})).toBeVisible()
  expect((await page.request.get('/api/v1/travel/itineraries')).status()).toBe(401)
})

test('saved versions deny a foreign source even when TEST ONLY client metadata is tampered',async({page,browser})=>{
  await login(page,'test-draft-beta')
  const own=(await(await page.request.get('/api/v1/travel/itineraries')).json()).items[0]
  const other=await browser.newContext({baseURL:process.env.E2E_BASE_URL})
  let foreign:any
  try {
    await other.route(/https:\/\//,route=>route.abort())
    const beta=await other.newPage();await beta.goto('/');await login(beta,'test-beta')
    foreign=(await(await beta.request.get('/api/v1/travel/itineraries')).json()).items[0]
  } finally {await other.close()}
  // TEST ONLY forged relationship, never persisted. The source read uses the real owner check.
  const forged={...own,parent_id:foreign.id}
  await page.route('**/api/v1/travel/itineraries',route=>route.fulfill({json:{items:[forged]}}))
  await page.route(`**/api/v1/travel/itineraries/${own.id}`,route=>route.fulfill({json:forged}))
  await saved(page)
  await page.locator('.saved-panel').getByRole('button',{name:'刷新',exact:false}).click()
  const denied=page.waitForResponse(response=>response.url().endsWith(`/itineraries/${foreign.id}`))
  await page.getByRole('button',{name:'对比来源版本',exact:true}).click()
  expect((await denied).status()).toBe(404)
  const compare=page.getByRole('region',{name:'已保存版本对照'})
  await expect(compare.getByRole('alert')).toContainText('版本对照暂不可用')
  await expect(compare.getByRole('table')).toHaveCount(0)
  await expect(compare).not.toContainText(foreign.title)
})

test('saved pagination keeps full history, foreign searches and cursor reuse scoped to one account',async({page,browser})=>{
  await login(page,'test-page-alpha')
  const own=await(await page.request.get('/api/v1/travel/itineraries',{params:{limit:100}})).json()
  expect(own.total).toBe(65)
  const other=await browser.newContext({baseURL:process.env.E2E_BASE_URL})
  let foreign:any
  try {
    await other.route(/https:\/\//,route=>route.abort())
    const beta=await other.newPage();await beta.goto('/');await login(beta,'test-page-beta')
    foreign=(await(await beta.request.get('/api/v1/travel/itineraries')).json()).items[0]
    const denied=await beta.request.get('/api/v1/travel/itineraries',{params:{cursor:own.page_cursor,limit:100}})
    expect(denied.status()).toBe(422)
    expect((await(await beta.request.get('/api/v1/travel/itineraries',{params:{query:own.items[0].id}})).json()).total).toBe(0)
  } finally {await other.close()}
  await saved(page)
  await page.getByRole('navigation',{name:'已保存行程分页'}).getByRole('button',{name:'下一页',exact:true}).click()
  await expect(page.locator('.saved-card')).toHaveCount(15)
  const allowed=new Set(own.items.map((item:any)=>item.id))
  expect((await page.locator('.saved-card').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('data-trip-id')))).every(id=>allowed.has(id))).toBe(true)
  await page.getByLabel('搜索已保存行程').fill(foreign.id)
  await expect(page.getByText('没有匹配的版本',{exact:true})).toBeVisible()
  await expect(page.locator('.saved-panel .version-scope').first()).toContainText('全库匹配 0 个版本')
})
