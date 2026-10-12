// Placement previews never spend resources or change the save.
(() => {
const map = document.querySelector('.map-scroll svg');
const preview = document.getElementById('placement-preview');
const column = document.getElementById('build-x');
const row = document.getElementById('build-y');
const kind = document.getElementById('building-type');
const rotation = document.getElementById('build-rotation');
if (!map || !preview || !column || !row || !kind || !rotation) return;
const bounds = {width: map.viewBox.baseVal.width, height: map.viewBox.baseVal.height};
let occupied = [...map.querySelectorAll('a > rect')].map(r => ({
  x: Number(r.getAttribute('x')), y: Number(r.getAttribute('y')),
  width: Number(r.getAttribute('width')), height: Number(r.getAttribute('height'))
}));
const hall = occupied[0];
window.addEventListener('map-occupied',event => {
  occupied = event.detail;
  updatePreview();
});
const submit = column.closest('form').querySelector('button[type="submit"]');
const budget = document.createElement('p'); budget.setAttribute('role','status');
column.closest('form').append(budget);
function affordability(stock) {
  const oldKind = kind.value;
  const list = document.getElementById('build-requirements');
  if (list) list.replaceChildren();
  for (const option of kind.options) {
    if (!option.value) continue;
    const reasons = [];
    let materialsMissing = false;
    if (Number(kind.dataset.hallLevel) < Number(option.dataset.unlock))
      reasons.push('Town Hall '+option.dataset.unlock+' required');
    for (const resource of ['scrap','metal','electronics']) {
      const short = Number(option.getAttribute('data-cost-'+resource)) - Number(stock[resource]);
      if (short > 0) {
        materialsMissing = true;
        reasons.push('Need '+Number(short.toFixed(2))+' more '+resource);
      }
    }
    option.disabled = reasons.length > 0;
    option.textContent = option.dataset.name + (reasons.length ? ' — '+reasons.join('; ') : '');
    if (list && reasons.length) {
      const item = document.createElement('li'); item.textContent = option.textContent;
      if (materialsMissing) {
        const marketLink = document.createElement('a');
        marketLink.href = '#market'; marketLink.textContent = 'Buy missing materials at the market';
        item.append(document.createTextNode(' · '), marketLink);
      }
      list.append(item);
    }
  }
  if (!kind.selectedOptions[0]?.value || kind.selectedOptions[0].disabled) {
    const available = [...kind.options].find(option => option.value && !option.disabled);
    kind.value = available ? available.value : '';
  }
  const selected = kind.selectedOptions[0];
  submit.disabled = kind.dataset.buildLocked === '1' || !selected?.value || selected.disabled;
  budget.textContent = selected?.value ? 'Cost: '+['scrap','metal','electronics']
    .map(r => selected.getAttribute('data-cost-'+r)+' '+r).join(' · ') :
    'No affordable unlocked buildings. Expand the requirements list to see what is missing.';
  if (oldKind !== kind.value) chooseNearby();
  updatePreview();
}
window.addEventListener('build-resources',event => affordability(event.detail));

const notice = document.createElement('p');
notice.className = 'placement-status'; notice.setAttribute('role', 'status');
const suggest = document.createElement('button');
suggest.type = 'button'; suggest.className = 'secondary';
suggest.textContent = 'Find nearby empty site';
column.closest('form').append(suggest, notice);
function dimensions() {
  const selected = kind.selectedOptions[0];
  if (!selected?.value) return null;
  let width = Number(selected.dataset.width), height = Number(selected.dataset.height);
  if (rotation.value === '90') [width, height] = [height, width];
  return {width, height};
}
function updatePreview() {
  const size = dimensions();
  preview.hidden = !size;
  preview.setAttribute('visibility',size ? 'visible' : 'hidden');
  if (!size) { notice.textContent = 'Select an available building to preview its footprint.'; return; }
  const {width, height} = size;
  const x = Number(column.value), y = Number(row.value);
  const fits = column.value !== '' && row.value !== '' && siteFits(x,y,width,height,bounds,occupied);
  for (const [key,value] of Object.entries({x,y,width,height})) preview.setAttribute(key,value);
  preview.classList.toggle('invalid-site', !fits);
  notice.textContent = fits ? 'Empty footprint selected. Check utilities, materials and workers before building.' :
    'This footprint overlaps occupied land or leaves the map. Choose another site.';
}
function chooseNearby() {
  if (!hall) return;
  const size = dimensions();
  if (!size) { updatePreview(); return; }
  const {width,height} = size;
  let site = nearbySite(width,height,bounds,occupied,hall);
  let rotated = false;
  if (!site && width !== height) {
    site = nearbySite(height,width,bounds,occupied,hall);
    if (site) { rotation.value = rotation.value === '90' ? '0' : '90'; rotated = true; }
  }
  if (!site) {
    column.value = ''; row.value = '';
    updatePreview();
    notice.textContent = 'No empty footprint is available for this building. Clear land or choose a smaller building.';
    return;
  }
  column.value = site.x; row.value = site.y; updatePreview();
  if (rotated) notice.textContent += ' Rotated to fit the available space.';
  const chosen = dimensions();
  window.dispatchEvent(new CustomEvent('map-preview-focus',{detail:{x:site.x,y:site.y,...chosen}}));
}
for (const control of [column,row]) control.addEventListener('input',updatePreview);
for (const control of [kind,rotation]) control.addEventListener('change',chooseNearby);
suggest.addEventListener('click',chooseNearby);
map.addEventListener('click', event => {
  if (event.target.closest('a')) return;
  const transform = map.getScreenCTM();
  if (!transform) return;
  const point = new DOMPoint(event.clientX,event.clientY).matrixTransform(transform.inverse());
  column.value = Math.max(0,Math.min(bounds.width-1,Math.floor(point.x)));
  row.value = Math.max(0,Math.min(bounds.height-1,Math.floor(point.y)));
  location.hash = 'screen-build';
  updatePreview();
});
affordability(Object.fromEntries(['scrap','metal','electronics'].map(r =>
  [r,Number(kind.getAttribute('data-available-'+r))])));
chooseNearby();
})();
