/** Vue number inputs may emit a number even without v-model.number. */
export function userPrices(ids: string[], values: Record<string,string|number>): Record<string,number> {
  const prices: Record<string,number>={}
  for(const id of ids) {
    const raw=values[id]
    if(raw===undefined || String(raw).trim()==='') continue
    const value=Number(raw)
    if(!Number.isFinite(value)||value<0) throw new Error('费用必须为非负数字')
    prices[id]=value
  }
  return prices
}
