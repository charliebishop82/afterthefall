// Market trades use the normal guarded POST exactly once; no page navigation.
function marketDetailKey(node){return node.querySelector('summary')?.textContent.split(' · ')[0].trim();}
function marketFormKey(form){return ['action','resource','unit_type'].map(name=>form.elements.namedItem(name)?.value||'').join(':');}
function marketError(body){
 if(!body.trim().startsWith('<'))return body.trim().slice(0,500)||'Market request rejected.';
 if(typeof DOMParser!=='undefined'){
  const alert=new DOMParser().parseFromString(body,'text/html').querySelector('[role="alert"]');
  if(alert)return alert.textContent.trim().slice(0,500);
 }
 return 'Market request rejected. Check your session and the player log.';
}
async function submitMarketOnce(fields,fetcher=fetch){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
 let response;
 try{response=await fetcher('/market',{method:'POST',credentials:'same-origin',redirect:'error',
  headers:{'Content-Type':'application/x-www-form-urlencoded','X-Market-Async':'1'},
  body:new URLSearchParams(fields),signal:controller.signal});}
 catch(error){throw new Error('Trade outcome is uncertain. Check market history and balances before submitting again.');}
 finally{clearTimeout(timer);}
 const requestId=response.headers.get('X-Request-ID');
 if(response.status!==204){
  const error=new Error(marketError(await response.text())+(requestId ? ' Request: '+requestId : ''));
  throw error;
 }
 return {requestId};
}
if(typeof module!=='undefined')module.exports={submitMarketOnce,marketFormKey,marketError};
if(typeof document!=='undefined')(()=>{
 let busy=false;
 const notice=document.createElement('p');notice.setAttribute('role','status');notice.hidden=true;
 function show(panel,text,error=false){notice.textContent=text;notice.className=error?'error':'';notice.hidden=false;panel.prepend(notice);}
 async function updatePanel(panel){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  let response;
  try{response=await fetch('/api/market-panel',{cache:'no-store',credentials:'same-origin',signal:controller.signal});}
  finally{clearTimeout(timer);}
  if(!response.ok)throw new Error('Could not refresh the market.');
  const parsed=new DOMParser().parseFromString(await response.text(),'text/html');
  const fresh=parsed.getElementById('market');if(!fresh)throw new Error('Invalid market response.');
  const drawer=panel.closest('.command-drawer'),scroll=drawer?.scrollTop;
  const open=new Map([...panel.querySelectorAll('details')].map(node=>[marketDetailKey(node),node.open]));
  const quantities=new Map([...panel.querySelectorAll('form')].map(form=>[marketFormKey(form),form.elements.namedItem('quantity')?.value]));
  // Keep the outer panel: menu navigation retains references to it.
  panel.replaceChildren(...fresh.childNodes);
  const explanation=panel.querySelector(':scope > p:first-of-type');
  if(explanation){const help=document.createElement('details');help.className='player-info';const title=document.createElement('summary');title.textContent='How this works';explanation.before(help);help.append(title,explanation);}
  for(const node of panel.querySelectorAll('details'))node.open=open.get(marketDetailKey(node))||false;
  for(const form of panel.querySelectorAll('form')){
   const input=form.elements.namedItem('quantity'),value=Number(quantities.get(marketFormKey(form)));
   if(input&&Number.isFinite(value)&&value>0)input.value=String(Math.max(Number(input.min)||1,Math.min(Number(input.max)||value,value)));
  }
  if(drawer)drawer.scrollTop=scroll;
 }
 document.addEventListener('submit',async event=>{
  const form=event.target,panel=form.closest('#market');
  if(!panel||form.getAttribute('action')!=='/market')return;
  event.preventDefault();if(busy)return;
  const fields=new FormData(form);busy=true;
  const buttons=[...panel.querySelectorAll('button')].map(button=>[button,button.disabled]);
  for(const [button] of buttons)button.disabled=true;
  show(panel,'Submitting trade…');
  try{
   const result=await submitMarketOnce(fields);
   window.dispatchEvent(new Event('refresh-supplies'));
   try{await updatePanel(panel);show(panel,'Trade completed.');}
   catch(error){show(panel,'Trade completed, but market details could not refresh. Check balances before another trade.'+(result.requestId?' Request: '+result.requestId:''),true);}
  }catch(error){show(panel,error.message,true);}
  finally{busy=false;for(const [button,disabled] of buttons)button.disabled=disabled;}
 });
})();
