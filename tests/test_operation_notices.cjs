const {test}=require('node:test'),assert=require('node:assert/strict');
const {operationCountdown,countdownLabel}=require('../static/operation-notices.js');
test('operations disappear only when server reports no active raids',()=>{
 assert.equal(operationCountdown({},5),null);assert.deepEqual(operationCountdown({'4':2},5),{count:1,seconds:0});assert.equal(countdownLabel(0),'Resolving…');
});
test('countdown follows earliest operation and respects paused clocks',()=>{
 assert.deepEqual(operationCountdown({'1':120,'2':300},15),{count:2,seconds:105});assert.equal(operationCountdown({'1':120},15,false).seconds,120);
 assert.equal(countdownLabel(65),'1:05');assert.equal(countdownLabel(3660),'1h 01m');
});
