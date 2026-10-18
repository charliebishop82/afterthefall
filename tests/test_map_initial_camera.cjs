const {test}=require('node:test');
const assert=require('node:assert/strict');
const {initialViewport}=require('../static/map-zoom.js');
test('player camera starts at oxygen coverage',()=>{
 assert.deepEqual(initialViewport({width:40,height:40},false,{x:16,y:16,width:8,height:8}),{x:16,y:16,width:8,height:8});
});
test('operator inspection retains its utility-area starting camera',()=>{
 const zones={x:10,y:11,width:20,height:18};
 assert.deepEqual(initialViewport({width:40,height:40},true,zones),zones);
});

test('coverage framing stays within map boundaries',()=>{
 assert.deepEqual(initialViewport({width:40,height:40},false,{x:-2,y:36,width:12,height:12}),{x:0,y:28,width:12,height:12});
});
