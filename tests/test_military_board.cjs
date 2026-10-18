const {test}=require('node:test');const assert=require('node:assert/strict');
const {equipmentMatches}=require('../static/military-board.js');
test('equipment filters distinguish availability, deployment and damage',()=>{
  const row={ready:0,deployed:2,damaged:1};
  assert.equal(equipmentMatches(row,'all'),true);assert.equal(equipmentMatches(row,'ready'),false);
  assert.equal(equipmentMatches(row,'deployed'),true);assert.equal(equipmentMatches(row,'damaged'),true);
  assert.equal(equipmentMatches(row,'unknown'),false);
});
