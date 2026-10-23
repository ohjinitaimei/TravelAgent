import { defineConfig } from '@playwright/test'
import { resolve, relative, isAbsolute } from 'node:path'
const suite=process.env.E2E_SUITE||(process.env.E2E_AUTH_TESTS==='1'?'auth':'local')

const output=process.env.E2E_OUTPUT_DIR
if(output){const path=relative(resolve('artifacts/browser-runs'),resolve(output));if(!path||path.startsWith('..')||isAbsolute(path))throw Error('Browser evidence must stay in its isolated run directory')}
export default defineConfig({
  testDir:'tests/browser',fullyParallel:false,workers:1,retries:0,timeout:30000,
  testMatch:suite==='resilience'?'**/resilience.spec.ts':suite==='auth'?'**/auth.spec.ts':['**/workspace.spec.ts','**/workflow.spec.ts','**/services.spec.ts'],
  expect:{timeout:15000},reporter:[['list'],['json',{outputFile:output?resolve(output,'report.json'):`artifacts/browser-reports/${process.env.E2E_BROWSER||'all'}/${suite}.json`}]],outputDir:output?resolve(output,'results'):`artifacts/browser-results/${process.env.E2E_BROWSER||'all'}/${suite}`,
  use:{baseURL:process.env.E2E_BASE_URL,viewport:{width:1440,height:1000},trace:'retain-on-failure',screenshot:'only-on-failure'},
  projects:['chromium','firefox','webkit'].map(name=>({name,use:{browserName:name as 'chromium'|'firefox'|'webkit'}})),
})
