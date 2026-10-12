const {test}=require('node:test');
const assert=require('node:assert/strict');
const {matchesMapFilter}=require('../static/map-filters.js');
test('all shows every footprint and each filter matches its own flag',()=>{
  const flags={unstaffed:true,stalled:false,damaged:true};
  assert.equal(matchesMapFilter(flags,'all'),true);
  assert.equal(matchesMapFilter(flags,'unstaffed'),true);
  assert.equal(matchesMapFilter(flags,'stalled'),false);
  assert.equal(matchesMapFilter(flags,'damaged'),true);
});
test('missing or unknown filters never fabricate an attention match',()=>{
  assert.equal(matchesMapFilter({},'damaged'),false);
  assert.equal(matchesMapFilter({damaged:true},'arbitrary'),false);
});
