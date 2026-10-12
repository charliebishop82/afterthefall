// Optional Node built-in geometry checks; no packages or live save required.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {clampViewport,frameZones,scaledViewport}=require('../static/map-zoom.js');
const bounds={width:40,height:40};
test('initial Oxygen frame includes padding and all coverage zones',()=>{
  assert.deepEqual(frameZones([{x:15,y:15,width:9,height:9}],bounds),
    {x:13,y:13,width:13,height:13});
  const frame=frameZones([{x:15,y:15,width:9,height:9},{x:27,y:18,width:5,height:5}],bounds);
  assert.equal(frame.x,13);assert.equal(frame.width,21);
});
test('coverage beyond map edges is clipped to playable bounds',()=>{
  assert.deepEqual(frameZones([{x:-4,y:-2,width:50,height:50}],bounds),
    {x:0,y:0,width:40,height:40});
});
test('Town Hall framing provides a small surrounding area',()=>{
  assert.deepEqual(frameZones([{x:18,y:18,width:3,height:3}],bounds,3),
    {x:15,y:15,width:9,height:9});
});
test('zoom preserves center until bounds require clamping',()=>{
  assert.deepEqual(scaledViewport({x:10,y:10,width:20,height:20},.5,bounds),
    {x:15,y:15,width:10,height:10});
  assert.deepEqual(scaledViewport({x:15,y:15,width:10,height:10},100,bounds),
    {x:0,y:0,width:40,height:40});
});
test('pan and extreme zoom stay bounded and do not mutate inputs',()=>{
  const view={x:-10,y:80,width:8,height:8};const original={...view};
  assert.deepEqual(clampViewport(view,bounds),{x:0,y:32,width:8,height:8});
  assert.equal(scaledViewport(view,.001,bounds).width,4);
  assert.deepEqual(view,original);
  assert.deepEqual(frameZones([],bounds),{x:0,y:0,width:40,height:40});
});
