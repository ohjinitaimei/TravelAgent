export type MapStatus='unconfigured'|'loading'|'ready'|'error'
type MapLoadingOptions<Sdk>={
  configured:boolean
  load:()=>Promise<Sdk>
  reset:()=>void
  draw:(sdk:Sdk)=>void
  destroy:()=>void
  status:(value:MapStatus)=>void
}

/** One visible map lifecycle. Only a user retry may reset a failed SDK loader. */
export class MapLoading<Sdk> {
  private sdk:Sdk|undefined
  private pending=false
  private disposed=false
  private generation=0
  private resetRequired=false
  state:MapStatus
  constructor(private readonly options:MapLoadingOptions<Sdk>){
    this.state=options.configured?'loading':'unconfigured'
    options.status(this.state)
  }
  private set(value:MapStatus){this.state=value;this.options.status(value)}
  start(){return this.attempt(false)}
  retry(){return this.attempt(true)}
  private async attempt(userRetry:boolean){
    if(this.disposed||!this.options.configured||this.pending||this.state==='ready'||this.state==='error'&&!userRetry)return
    this.pending=true
    const generation=++this.generation
    let sdkLoaded=false
    this.set('loading')
    try{
      this.options.destroy()
      if(this.resetRequired){this.options.reset();this.resetRequired=false}
      const sdk=await this.options.load()
      sdkLoaded=true
      if(this.disposed||generation!==this.generation)return
      this.sdk=sdk
      this.options.draw(sdk)
      this.set('ready')
    }catch{
      if(this.disposed||generation!==this.generation)return
      this.resetRequired=!sdkLoaded
      this.sdk=undefined
      this.clean()
      this.set('error')
    }finally{
      if(generation===this.generation)this.pending=false
    }
  }
  redraw(){
    if(this.disposed||this.pending||this.state!=='ready'||this.sdk===undefined)return
    try{this.options.draw(this.sdk)}
    catch{this.sdk=undefined;this.clean();this.set('error')}
  }
  private clean(){try{this.options.destroy()}catch{/* Preserve a safe error/disposed state even if the SDK cleanup itself fails. */}}
  dispose(){
    this.disposed=true;this.generation++;this.pending=false;this.sdk=undefined;this.clean()
  }
}
