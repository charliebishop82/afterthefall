// Progress is committed by the server. Never submit player actions from this page.
if(typeof document!=='undefined')(()=>{
 const panel=document.getElementById('catchup-progress');if(!panel)return;
 const message=document.getElementById('catchup-message'),bar=document.getElementById('catchup-bar'),retry=document.getElementById('catchup-retry');
 const query=panel.dataset.shared==='bank'?'?scope=bank':'';
 let initial=null,busy=false,finished=false,stepTimer=null,statusTimer=null,failures=0;
 async function read(url,timeout){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try{
   const response=await fetch(url,{cache:'no-store',signal:controller.signal});
   if(response.status===401){finished=true;location.replace('/login');return null;}
   if(!response.ok)throw new Error('Catch-up temporarily unavailable');
   return await response.json();
  }finally{clearTimeout(timer);}
 }
 function render(state){
  if(!state||finished)return;
  if(state.status==='ready'){
   finished=true;clearTimeout(stepTimer);clearTimeout(statusTimer);bar.value=100;
   message.textContent='World updated. Opening your settlement…';retry.hidden=true;
   location.replace('/'+location.hash);return;
  }
  if(state.status!=='catching_up')throw new Error('Unexpected progress response');
  if(initial===null)initial=Math.max(1,state.remaining_seconds);
  bar.value=Math.max(bar.value,Math.min(99,(1-state.remaining_seconds/initial)*100));
  message.textContent=state.settlements_remaining+' settlements updating · '+(state.remaining_seconds/3600).toFixed(1)+' combined settlement-hours remaining. This is game time, not a wait estimate.';
 }
 async function advance(){
  if(busy||finished)return;busy=true;retry.hidden=true;
  try{render(await read('/api/catchup'+query,35000));failures=0;}
  catch(_){if(!finished){failures++;message.textContent='Connection delayed. Progress is saved; retrying automatically…';retry.hidden=false;}}
  finally{busy=false;if(!finished)stepTimer=setTimeout(advance,failures?Math.min(15000,2000*failures):250);}
 }
 // This read-only check can detect completion by the background coordinator even
 // while a simulation request is delayed. It never starts another simulation batch.
 async function check(){
  if(finished)return;
  try{render(await read('/api/catchup-status'+query,10000));}catch(_){}
  finally{if(!finished)statusTimer=setTimeout(check,3000);}
 }
 retry.addEventListener('click',()=>{clearTimeout(stepTimer);advance();});
 window.addEventListener('pagehide',()=>{finished=true;clearTimeout(stepTimer);clearTimeout(statusTimer);});
 advance();statusTimer=setTimeout(check,1500);
})();
