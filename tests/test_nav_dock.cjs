const {test}=require('node:test');const assert=require('node:assert/strict');
const {NAV_ICONS,NAV_LABELS,menuCategory}=require('../static/player-ui.js');
test('every main page has an icon and a visible concise label',()=>{
  const pages=['overview','build','citizens','economy','military','social'];
  assert.deepEqual(Object.keys(NAV_ICONS),pages);
  for(const page of pages){assert.ok(NAV_ICONS[page].startsWith('M'));assert.ok(NAV_LABELS[page]);}
});
test('military expedition and market navigation retain existing destinations',()=>{
  assert.equal(menuCategory('expeditions','Explore the Wastes'),'military');
  assert.equal(menuCategory('market','Public market'),'economy');
  assert.equal(menuCategory('citizens','Citizens'),'citizens');
});
