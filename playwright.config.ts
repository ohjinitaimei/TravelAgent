import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir:'tests/browser',fullyParallel:false,workers:1,retries:0,timeout:30000,
  expect:{timeout:15000},reporter:'list',outputDir:'artifacts/browser-results',
  use:{baseURL:process.env.E2E_BASE_URL,viewport:{width:1440,height:1000},trace:'retain-on-failure',screenshot:'only-on-failure'},
  projects:[{name:'chromium',use:{browserName:'chromium'}}],
})
