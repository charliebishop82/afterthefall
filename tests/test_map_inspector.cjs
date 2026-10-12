const {test}=require('node:test');
const assert=require('node:assert/strict');
const {inspectableAnchor}=require('../static/map-inspector.js');
test('only known structure anchors open management controls',()=>{
  for (const target of ['town-hall','building-12','derelict-4','ruin-7'])
    assert.equal(inspectableAnchor('#'+target),target);
});
test('external urls, unrelated sections and malformed IDs cannot open inspector',()=>{
  for (const target of [null,'https://example.com/#building-1','#screen-build','#building-0','#building--1','#building-1-extra'])
    assert.equal(inspectableAnchor(target),null);
});
