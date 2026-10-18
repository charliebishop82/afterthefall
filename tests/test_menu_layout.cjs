const {test}=require('node:test');const assert=require('node:assert/strict');
const {preferredPane}=require('../static/menu-layout.js');
test('economy opens the market when available',()=>{
 const rows=[{id:'rations'},{id:'market'},{id:'bank'}];assert.equal(preferredPane(rows,'economy'),rows[1]);
});
test('diplomacy opens treaties and overview opens alerts',()=>{
 const rows=[{id:'messages'},{id:'diplomacy'},{id:'attention'}];
 assert.equal(preferredPane(rows,'social'),rows[1]);assert.equal(preferredPane(rows,'overview'),rows[2]);
});
test('dashboard menus retain their first existing pane and missing defaults fall back',()=>{
 const rows=[{id:'military-dashboard'},{id:'conflict'}];assert.equal(preferredPane(rows,'military'),rows[0]);assert.equal(preferredPane(rows,'economy'),rows[0]);
});
test('empty menus do not invent a pane',()=>{assert.equal(preferredPane([],'citizens'),undefined);});
