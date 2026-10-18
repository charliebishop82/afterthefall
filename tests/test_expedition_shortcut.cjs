const {test}=require('node:test'),assert=require('node:assert/strict');
const {expeditionSummary}=require('../static/expedition-shortcut.js');
test('no shortcut for absent or completed expeditions',()=>{assert.equal(expeditionSummary([]),null);assert.equal(expeditionSummary([{status:'returned',crew:['A'],seconds:0}]),null);});
test('summary counts citizens and shows the earliest scheduled return',()=>{
 const result=expeditionSummary([{status:'exploring',crew:['A','B'],seconds:721},{status:'returning',crew:['C'],seconds:119}]);
 assert.equal(result.citizens,3);assert.equal(result.trips,2);assert.equal(result.minutes,2);assert.equal(result.returning,false);
});
test('returning parties remain visible until their return is committed',()=>{
 const result=expeditionSummary([{status:'returning',crew:['A'],seconds:0}]);assert.equal(result.returning,true);assert.equal(result.minutes,0);
});
