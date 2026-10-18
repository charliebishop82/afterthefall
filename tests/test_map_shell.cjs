const {test}=require('node:test');const assert=require('node:assert/strict');
const {MAP_PURPOSES,visibleCard,stateBadge}=require('../static/map-shell.js');
test('manual list filtering ignores case and trims the query',()=>{
  assert.equal(visibleCard('Small Offensive Drone Hangar',' DRONE '),true);
  assert.equal(visibleCard('Garden','water'),false);
  assert.equal(visibleCard('Garden',''),true);
});
test('status symbols prioritize damage and have explanatory text',()=>{
  assert.deepEqual(stateBadge({damaged:true,unstaffed:true}),['!','Damaged structure']);
  assert.deepEqual(stateBadge({stalled:true}),['Ⅱ','Work is stalled']);
  assert.deepEqual(stateBadge({unstaffed:true}),['○','Operating workers needed']);
  assert.equal(stateBadge({}),null);
});
test('purpose legend uses separate labelled resource and utility colours',()=>{
  const colors=Object.fromEntries(MAP_PURPOSES);
  assert.notEqual(colors.Water,colors.Oxygen);
  assert.notEqual(colors.Food,colors.Military);
  assert.ok(colors.Storage);
});
