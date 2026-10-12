// Optional Node built-in tests; no npm packages or live game required.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {siteFits,nearbySite} = require('../static/placement.js');
const bounds = {width:6,height:6};
const hall = {x:2,y:2,width:2,height:2};
test('nearest empty footprint stays beside the hall', () => {
  const site = nearbySite(2,2,bounds,[hall],hall);
  assert.ok(siteFits(site.x,site.y,2,2,bounds,[hall]));
  assert.equal(Math.hypot(site.x-2,site.y-2),2);
});
test('edges touching are available but partial overlap is blocked', () => {
  assert.equal(siteFits(0,2,2,2,bounds,[hall]),true);
  assert.equal(siteFits(1,2,2,2,bounds,[hall]),false);
});
test('rectangular rotated footprints obey map bounds', () => {
  assert.equal(siteFits(4,3,2,3,bounds,[]),true);
  assert.equal(siteFits(4,3,3,2,bounds,[]),false);
});
test('fully occupied map and oversized buildings have no suggestion', () => {
  assert.equal(nearbySite(1,1,bounds,[{x:0,y:0,width:6,height:6}],hall),null);
  assert.equal(nearbySite(7,1,bounds,[],hall),null);
});
test('ruins are blockers, coordinates are integral, inputs stay unchanged', () => {
  const occupied=[hall,{x:0,y:0,width:2,height:2}];
  const before=JSON.stringify(occupied);
  assert.equal(siteFits(0,0,1,1,bounds,occupied),false);
  assert.equal(siteFits(.5,0,1,1,bounds,[]),false);
  nearbySite(1,1,bounds,occupied,hall);
  assert.equal(JSON.stringify(occupied),before);
});

test('large building skips small gaps and finds its whole footprint', () => {
  const area={width:12,height:12};
  const blockers=[{x:4,y:4,width:3,height:3},{x:0,y:0,width:3,height:3}];
  const site=nearbySite(4,4,area,blockers,blockers[0]);
  assert.ok(site);
  assert.equal(siteFits(site.x,site.y,4,4,area,blockers),true);
});
test('a rectangle can fit rotated even when its normal orientation cannot', () => {
  const area={width:3,height:6};
  assert.equal(nearbySite(4,2,area,[],hall),null);
  assert.ok(nearbySite(2,4,area,[],hall));
});
