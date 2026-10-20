/** Keep Tab inside the modal instead of moving to browser chrome at either edge. */
export function keepDialogFocus(event:KeyboardEvent) {
  if(event.key!=='Tab'||!(event.currentTarget instanceof HTMLDialogElement))return
  const dialog=event.currentTarget
  const items=Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])')).filter(item=>item.getClientRects().length>0)
  const first=items[0],last=items.at(-1)
  if(!first){event.preventDefault();dialog.focus();return}
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
}
