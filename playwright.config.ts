import { defineConfig } from '@playwright/test'
const suite=process.env.E2E_SUITE||(process.env.E2E_AUTH_TESTS==='1'?'auth':'local')

export default defineConfig({
  testDir:'tests/browser',fullyParallel:false,workers:1,retries:0,timeout:30000,
  testMatch:suite==='resilience'?'**/resilience.spec.ts':suite==='auth'?'**/auth.spec.ts':'**/workspace.spec.ts',
  expect:{timeout:15000},reporter:[['list'],['json',{outputFile:`artifacts/browser-reports/${process.env.E2E_BROWSER||'all'}/${suite}.json`}]],outputDir:`artifacts/browser-results/${process.env.E2E_BROWSER||'all'}/${suite}`,
  use:{baseURL:process.env.E2E_BASE_URL,viewport:{width:1440,height:1000},trace:'retain-on-failure',screenshot:'only-on-failure'},
  projects:['chromium','firefox','webkit'].map(name=>({name,use:{browserName:name as 'chromium'|'firefox'|'webkit'}})),
})
