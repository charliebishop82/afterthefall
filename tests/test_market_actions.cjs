const {test}=require('node:test'),assert=require('node:assert/strict');
const {submitMarketOnce,marketFormKey,marketError}=require('../static/market-actions.js');
const response=(status,body='')=>({status,headers:{get:()=> 'request-id'},text:async()=>body});
test('a confirmed trade submits once using ordinary URL-encoded fields and no redirect',async()=>{
 let calls=0;const result=await submitMarketOnce([['token','csrf'],['action','sell'],['quantity','2']],async(url,options)=>{
  calls++;assert.equal(url,'/market');assert.equal(options.redirect,'error');assert.equal(options.headers['X-Market-Async'],'1');assert.equal(options.body.get('token'),'csrf');return response(204);
 });assert.equal(calls,1);assert.equal(result.requestId,'request-id');
});
test('server rejection remains an error and is never replayed',async()=>{
 let calls=0;await assert.rejects(submitMarketOnce([],async()=>{calls++;return response(400,'Free storage space first.');}),/Free storage space first/);assert.equal(calls,1);
});
test('transport failure warns of an uncertain outcome without retry',async()=>{
 let calls=0;await assert.rejects(submitMarketOnce([],async()=>{calls++;throw new Error('network');}),/outcome is uncertain/);assert.equal(calls,1);
});
test('unexpected success page is not reported as a confirmed trade',async()=>{
 await assert.rejects(submitMarketOnce([],async()=>response(200,'<html>Login</html>')),/Market request rejected/);
});
test('quantity preservation distinguishes resource and equipment forms',()=>{
 const form=values=>({elements:{namedItem:name=>values[name]===undefined?null:{value:values[name]}}});
 assert.notEqual(marketFormKey(form({action:'buy',resource:'scrap'})),marketFormKey(form({action:'buy',resource:'metal'})));
 assert.notEqual(marketFormKey(form({action:'equipment_buy',unit_type:'offensive_drone'})),marketFormKey(form({action:'equipment_buy',unit_type:'repair_drone'})));
 assert.equal(marketError('<html>Hidden token</html>'),'Market request rejected. Check your session and the player log.');
});
