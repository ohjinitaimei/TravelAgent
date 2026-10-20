import { build, createServer, preview } from 'vite'
import { existsSync } from 'node:fs'
import { resolve, relative, isAbsolute } from 'node:path'

const config={configFile:resolve('apps/web/vite.config.ts'),root:resolve('apps/web')}
let server
if(process.env.E2E_SUITE==='resilience') {
  const outDir=resolve(process.env.E2E_BUILD_DIR||'.'),inside=relative(resolve('.tmp'),outDir)
  if(!inside||inside.startsWith('..')||isAbsolute(inside))throw Error('Production acceptance build must stay inside the isolated .tmp folder')
  await build({...config,build:{outDir,emptyOutDir:true}})
  server=await preview({...config,build:{outDir},preview:{host:'127.0.0.1',port:Number(process.env.E2E_WEB_PORT),strictPort:true,proxy:{'/api':{target:process.env.TRAVEL_BACKEND_URL,changeOrigin:true}}}})
} else {
  server=await createServer({...config,server:{host:'127.0.0.1',port:Number(process.env.E2E_WEB_PORT),strictPort:true}})
  await server.listen()
}
const timer=setInterval(async()=>{
  if(existsSync(process.env.E2E_STOP_FILE)) {clearInterval(timer);await (server.close?server.close():new Promise(resolve=>server.httpServer.close(resolve)));process.exit(0)}
},100)
