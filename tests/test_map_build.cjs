const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {nextBuildRotation}=require('../static/map-build.js');
test('rotate button alternates supported orientations',()=>{
  assert.equal(nextBuildRotation('0'),'90');assert.equal(nextBuildRotation('90'),'0');
});
test('overlay reuses original form and restores it instead of cloning controls',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../static/map-build.js'),'utf8');
  assert.ok(source.includes('form.before(formPlaceholder);body.append(form)'));
  assert.ok(source.includes('formPlaceholder.replaceWith(form)'));
  assert.ok(!source.includes('cloneNode'));
});
test('map build entry switches pan off through the existing mode control',()=>{
  const source=fs.readFileSync(path.join(__dirname,'../static/map-zoom.js'),'utf8');
  assert.ok(source.includes("window.addEventListener('map-build-open'"));
  assert.ok(source.includes('if(pan)mode.click()'));
});
