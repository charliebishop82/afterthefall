const {test}=require('node:test'),assert=require('node:assert/strict');
const {xpProgress}=require('../static/citizen-xp.js');
test('XP within a level uses cumulative thresholds',()=>{
 assert.deepEqual(xpProgress(2,130,[0,100,250]),{maximum:false,remaining:120,target:250,span:150,earned:30});
});
test('maximum level has a full bar and no further requirement',()=>{
 const p=xpProgress(3,500,[0,100,250]);assert.equal(p.maximum,true);assert.equal(p.earned,p.span);assert.equal(p.remaining,0);
});
test('progress stays inside the bar around level boundaries',()=>{
 assert.equal(xpProgress(2,100,[0,100,250]).earned,0);assert.equal(xpProgress(1,110,[0,100,250]).earned,100);
});
