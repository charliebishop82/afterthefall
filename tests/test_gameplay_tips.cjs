const {test}=require('node:test');
const assert=require('node:assert/strict');
const {GAMEPLAY_TIPS,tipDue,pickTip}=require('../static/gameplay-tips.js');
test('automatic tips respect disable preference, interval and daily maximum',()=>{
  const now=2*86400000+1000000;
  assert.equal(tipDue({disabled:true},now),false);
  assert.equal(tipDue({last:now-599999},now),false);
  assert.equal(tipDue({last:now-600000},now),true);
  assert.equal(tipDue({day:2,count:3,last:0},now),false);
  assert.equal(tipDue({day:1,count:3,last:0},now),true);
});
test('selection avoids recently seen tips and starts another cycle when all seen',()=>{
  const tips=[{id:'a'},{id:'b'}];
  assert.equal(pickTip(tips,['a'],()=>0).id,'b');
  assert.equal(pickTip(tips,['a','b'],()=>0).id,'a');
});
test('tips have unique identities and only navigate within the game',()=>{
  assert.equal(new Set(GAMEPLAY_TIPS.map(t=>t.id)).size,GAMEPLAY_TIPS.length);
  for(const tip of GAMEPLAY_TIPS){assert.ok(tip.text.length>0);assert.ok(tip.link.startsWith('#'));assert.ok(tip.label);}
});
