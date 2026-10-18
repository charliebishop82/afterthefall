const {test}=require('node:test');const assert=require('node:assert/strict');
const {citizenMatches,sortCitizens,citizenInitials}=require('../static/citizen-board.js');
test('filters distinguish free, working, away and injured citizens',()=>{
  const c={free:false,away:true,hp:50,max_hp:100};
  assert.equal(citizenMatches(c,'away'),true);assert.equal(citizenMatches(c,'injured'),true);
  assert.equal(citizenMatches(c,'free'),false);assert.equal(citizenMatches(c,'working'),false);
  assert.equal(citizenMatches({free:false,away:false},'working'),true);
});
test('health sorts by fraction and level sort preserves the original roster',()=>{
  const rows=[{id:1,name:'A',level:1,hp:80,max_hp:100},{id:2,name:'B',level:3,hp:90,max_hp:200}];
  assert.deepEqual(sortCitizens(rows,'health').map(c=>c.id),[2,1]);
  assert.deepEqual(sortCitizens(rows,'level').map(c=>c.id),[2,1]);assert.equal(rows[0].id,1);
});
test('avatars have simple initials without creating portrait assets',()=>{
  assert.equal(citizenInitials('Alex Ash'),'AA');assert.equal(citizenInitials('Sam'),'S');
});
