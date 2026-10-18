const {test}=require('node:test');const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/catchup.js'),'utf8');
function page(fetch){
 const timers=[],redirects=[];const nodes={'catchup-progress':{dataset:{}},'catchup-message':{},'catchup-bar':{value:0},'catchup-retry':{addEventListener(){}}};
 vm.runInNewContext(source,{document:{getElementById:id=>nodes[id]},fetch,AbortController,location:{hash:'#screen-build',replace:url=>redirects.push(url)},window:{addEventListener(){}},setTimeout:(callback,delay)=>{const timer={callback,delay};timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.cancelled=true;}});
 return {timers,redirects,nodes};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('ready batch automatically opens the settlement and preserves its selected menu',async()=>{
 const p=page(async()=>({ok:true,status:200,json:async()=>({status:'ready'})}));await settle();
 assert.deepEqual(p.redirects,['/#screen-build']);assert.equal(p.nodes['catchup-bar'].value,100);
});
test('a failed request retries automatically rather than requiring manual intervention',async()=>{
 let calls=0;const p=page(async()=>{if(++calls===1)throw Error('offline');return {ok:true,status:200,json:async()=>({status:'ready'})};});await settle();
 const retry=p.timers.find(t=>t.delay===2000&&!t.cancelled);assert.ok(retry);await retry.callback();await settle();
 assert.deepEqual(p.redirects,['/#screen-build']);
});
test('read-only readiness can open the game while the batch request is delayed',async()=>{
 const p=page(url=>url.startsWith('/api/catchup-status')?Promise.resolve({ok:true,status:200,json:async()=>({status:'ready'})}):new Promise(()=>{}));
 await p.timers.find(t=>t.delay===1500).callback();await settle();assert.deepEqual(p.redirects,['/#screen-build']);
});
