const {test} = require('node:test');
const assert = require('node:assert/strict');
const {panelChanges,clockDescription} = require('../static/live-refresh.js');
test('unchanged snapshots do not request new panels', () => {
  assert.equal(panelChanges({revision:'a',status:'active'},'a','active'),false);
});
test('new controls and season status changes request panels', () => {
  assert.equal(panelChanges({revision:'b',status:'active'},'a','active'),true);
  assert.equal(panelChanges({revision:'a',status:'paused'},'a','active'),true);
});
test('clock text reflects running, frozen and completed states', () => {
  assert.match(clockDescription('paused'),/paused/);
  assert.match(clockDescription('suspended'),/frozen/);
  assert.match(clockDescription('finished'),/finished/);
});
