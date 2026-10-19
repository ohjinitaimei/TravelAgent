import { createServer } from 'vite'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const server=await createServer({configFile:resolve('apps/web/vite.config.ts'),root:resolve('apps/web'),server:{host:'127.0.0.1',port:Number(process.env.E2E_WEB_PORT),strictPort:true}})
await server.listen()
const timer=setInterval(async()=>{
  if(existsSync(process.env.E2E_STOP_FILE)) {clearInterval(timer);await server.close();process.exit(0)}
},100)
