const {test}=require('node:test');
const assert=require('node:assert/strict');
const {menuCategory}=require('../static/player-ui.js');
test('all combat headings remain in Military, including Citizen raids',()=>{
  for (const heading of ['Citizen raids','Citizen and drone raids'])
    assert.equal(menuCategory('conflict',heading),'military');
  assert.equal(menuCategory('','Structural combat'),'military');
});
test('production and drone servicing stay in Military',()=>{
  assert.equal(menuCategory('military','Military production'),'military');
  assert.equal(menuCategory('maintenance','Drone maintenance'),'military');
});
test('citizen management and other systems keep their own menus',()=>{
  assert.equal(menuCategory('citizens','Citizens'),'citizens');
  assert.equal(menuCategory('','Citizen wellbeing'),'citizens');
  assert.equal(menuCategory('scavenging','Active scavenging'),'build');
  assert.equal(menuCategory('needs','Supplies and rations'),'economy');
  assert.equal(menuCategory('messages','Player messages'),'social');
  assert.equal(menuCategory('attention','Needs attention'),'overview');
});
