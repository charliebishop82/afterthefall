// The server owns time and quantities. This script only refreshes their display.
const clockPanel = document.querySelector('.clock-controls');
const connectionStatus = document.getElementById('connection-status');

const shortageNotice = document.createElement('p');
shortageNotice.className = 'error'; shortageNotice.setAttribute('role','status'); shortageNotice.hidden = true;
clockPanel.after(shortageNotice);
const updateNotice = document.createElement('span');
const updatePanels = document.createElement('button');
updatePanels.type = 'button'; updatePanels.className = 'secondary update-panels-button'; updatePanels.hidden = true;
updatePanels.textContent = 'Update panels';
updateNotice.setAttribute('role','status');updateNotice.className='panel-update-notice';
updatePanels.title='Refresh menus and events. Unsent form entries will reset.';
connectionStatus.after(updateNotice, updatePanels);
updatePanels.addEventListener('click', () => {
  // Only this explicit click reloads controls, never a background poll.
  try {
    sessionStorage.setItem('panel-scroll',JSON.stringify({x:scrollX,y:scrollY,
      details:[...document.querySelectorAll('details')].map(node => node.open),
      mapX:document.querySelector('.map-scroll')?.scrollLeft || 0,
      mapY:document.querySelector('.map-scroll')?.scrollTop || 0}));
  } catch (_) {}
  window.location.reload();
});
function setText(id,value) {
  const node = document.getElementById(id); if (node) node.textContent = value;
}
function updateScavengingMarker(id, percent) {
  const marker = document.getElementById('map-scavenging-'+id);
  if (!marker) return;
  const recovered = Math.max(0,Math.min(100,Number(percent)));
  const label = 'Scavenging: '+Math.round(recovered)+'% recovered';
  marker.setAttribute('aria-label',label);
  const title = marker.querySelector('title'); if (title) title.textContent = label;
  const bar = marker.querySelector('.scavenge-remaining');
  if (bar) bar.setAttribute('stroke-dasharray',(100-recovered)+' 100');
  const anchor = marker.closest('a');
  const anchorTitle = anchor?.querySelector(':scope > title');
  if (anchorTitle) {
    if (!anchor.dataset.scavengeTitle) anchor.dataset.scavengeTitle = anchorTitle.textContent;
    anchorTitle.textContent = anchor.dataset.scavengeTitle+' · '+label;
  }
}
let lastResourceAlerts = null;
function updateResourceAlerts(rows) {
  const signature=JSON.stringify(rows);
  if (signature===lastResourceAlerts) return;
  lastResourceAlerts=signature;
  const list=document.getElementById('resource-alert-list');
  if (list) {
    list.replaceChildren();
    for (const alert of rows) {
      const item=document.createElement('li'); item.className='attention-'+alert.severity;
      const message=document.createElement('strong'); message.textContent=alert.message;
      const link=document.createElement('a');link.href=alert.link;link.textContent=alert.label;
      item.append(message,document.createTextNode(' '),link);list.append(item);
    }
  }
  const empty=document.getElementById('resource-alert-empty');if (empty) empty.hidden=rows.length>0;
  for (const resource of ['food','water','scrap','metal','electronics','credits']) {
    const amount=document.getElementById('amount-'+resource);if (!amount) continue;
    let badge=amount.parentElement.querySelector('.resource-warning');
    const applicable=rows.filter(row=>row.resources.includes(resource));
    if (!applicable.length) { if (badge) badge.remove(); continue; }
    if (!badge) {
      badge=document.createElement('a');badge.className='resource-warning';
      badge.textContent='⚠';badge.href='#attention';amount.before(badge);
    }
    badge.title=applicable.map(row=>row.message).join(' ');
    badge.setAttribute('aria-label',resource+' warning: '+badge.title);
  }
}
async function refreshSupplies() {
  try {
    const response = await fetch('/api/resources', {cache: 'no-store'});
    if (!response.ok) throw new Error('Could not read supplies');
    const state = await response.json();
    if (state.status === 'catching_up') { window.location.reload(); return; }
    updateResourceAlerts(state.resource_alerts || []);
    window.dispatchEvent(new CustomEvent('map-filter-state',{detail:state.map_filters || {}}));
    shortageNotice.hidden = state.food > 0 && state.water > 0;
    shortageNotice.textContent = 'Food or Water is depleted. Check production and rations: shortage health consequences may apply.';
    const changed = panelChanges(state,clockPanel.dataset.revision,clockPanel.dataset.status);
    updatePanels.hidden = !changed;
    updateNotice.textContent = changed ? ' New controls or events are available. Update panels when ready (unsent forms will reset).' : '';
    setText('clock-label',clockDescription(state.status));
    // Freeze stale action controls immediately; only a fresh panel may re-enable them.
    if (state.status === 'paused' || state.status === 'finished') {
      for (const form of document.querySelectorAll('form')) {
        if (/^\/(buildings|scavenging|needs|manufacturing|administrator|trade|conflict|expeditions|market|diplomacy|bank|advisor)$/.test(form.getAttribute('action'))) {
          for (const control of form.elements) control.disabled = true;
        }
      }
    }
    if (state.map_occupied) window.dispatchEvent(new CustomEvent('map-occupied',{detail:state.map_occupied}));
    for (const [id,hint] of Object.entries(state.building_staffing || {})) {
      const card=document.getElementById('building-'+id);
      const warning=document.getElementById('staffing-warning-'+id);
      if (card) card.classList.toggle('unstaffed-building',hint.unstaffed);
      if (warning) {
        warning.hidden=!hint.unstaffed;
        warning.textContent=hint.label+' · open staffing controls below';
      }
    }
    const buildKind = document.getElementById('building-type');
    if (buildKind) {
      buildKind.dataset.buildLocked = state.build_locked || state.status === 'paused' ? '1' : '0';
      buildKind.dataset.hallLevel = state.hall_level;
    }
    for (const id of state.completed_jobs || []) {
      setText('map-job-'+id,'100%');
      updateScavengingMarker(id,100);
      setText('map-eta-'+id,'Done');
      setText('scavenge-eta-'+id,'Done');
      setText('scavenge-percent-'+id,'100% recovered');
      setText('scavenge-yield-'+id,'No current yield');
      setText('scavenge-workers-'+id,'0');
      const scavengingProgress=document.getElementById('scavenge-progress-'+id);
      if (scavengingProgress) scavengingProgress.value=100;
      setText('job-'+id,'Completed — update panels for new controls.');
      const progress = document.getElementById('progress-'+id); if (progress) progress.value = 100;
    }
    setText('amount-credits',Number(state.credits).toFixed(2));
    for(const row of state.expeditions || []) {
      setText('expedition-status-'+row.id,row.status==='returned'?'Returned':row.status==='exploring'?'Exploring':'Returning');
      setText('expedition-elapsed-'+row.id,'Active time away: '+Math.floor(row.elapsed/60)+' min');
      setText('expedition-summary-'+row.id,row.status==='returned'?'Returned — home':row.status+' · home in '+Math.ceil(row.seconds/60)+' min');
      setText('expedition-eta-'+row.id,row.status==='returned'?'Home — update panels for delivery details':'Home in '+Math.ceil(row.seconds/60)+' min');
      setText('expedition-haul-'+row.id,'Gathered: '+Object.entries(row.haul).map(([r,q])=>q.toFixed(1)+' '+r).join(' · '));
      const recall=document.getElementById('expedition-recall-'+row.id);if(recall)recall.disabled=row.status!=='exploring';
    }

    if (state.defense) {
      setText('ground-defense',Number(state.defense.total).toFixed(1));
      const help=document.getElementById('defense-help');
      if (help) { help.title=state.defense.description; help.setAttribute('aria-label','Ground defense: '+state.defense.description); }
    }
    if (state.citizen_counts) {
      setText('citizens-total',state.citizen_counts.total);
      setText('citizens-free',state.citizen_counts.free);
    }
    for (const [resource,rate] of Object.entries(state.rates || {})) {
      const cells = document.querySelector('[data-resource-rate="'+resource+'"]')?.cells;
      if (cells) {
        cells[1].textContent = '+'+Number(rate.production).toFixed(2);
        cells[2].textContent = '−'+Number(rate.consumption).toFixed(2);
        cells[3].textContent = Number(rate.net).toFixed(2);
      }
    }
    for (const citizen of state.citizens || []) {
      const cells = document.querySelector('[data-citizen-id="'+citizen.id+'"]')?.cells;
      if (!cells) continue;
      cells[1].textContent = citizen.level + (citizen.show_xp ? ' · '+Number(citizen.xp).toFixed(2)+' XP' : '');
      cells[2].textContent = Number(citizen.hp).toFixed(2)+' HP';
      const assignment = cells[4].querySelector('.role');
      if (assignment) assignment.textContent = citizen.assignment;
      cells[6].textContent = Number(citizen.morale).toFixed(2) +
        (citizen.housing_modifier ? ' ('+(citizen.housing_modifier>0 ? '+' : '')+citizen.housing_modifier+' housing)' : '');
    }
    for (const [anchor,required] of Object.entries(state.map_staff_required || {})) {
      const marker=document.querySelector('.map-scroll a[href="#'+anchor+'"] .map-people');
      if (marker) marker.setAttribute('visibility',required ? 'visible' : 'hidden');
    }
    for (const [anchor,count] of Object.entries(state.map_staff || {})) {
      const badge = document.querySelector('.map-scroll a[href="#'+anchor+'"] .map-people .map-staff');
      if (badge) { badge.textContent = count; const label=badge.parentElement.querySelector('title'); if (label) label.textContent=count+' assigned citizens'; }
    }
    for (const [id, job] of Object.entries(state.jobs || {})) {
      const label = document.getElementById(`job-${id}`);
      const progress = document.getElementById(`progress-${id}`);
      if (label) label.textContent = job.label;
      if (progress) progress.value = job.percent;
      setText('map-job-'+id,Math.round(job.percent)+'%');
      updateScavengingMarker(id,job.percent);
      setText('map-eta-'+id,'ETA '+job.eta);
    }
    const scavenged={scrap:0,metal:0,electronics:0};
    for (const site of state.scavenging || []) {
      for (const resource of Object.keys(scavenged)) scavenged[resource]+=Number(site.rates[resource] || 0);
    }
    for (const resource of Object.keys(scavenged)) {
      const rate=state.rates?.[resource];if (!rate) continue;
      const net=Number(rate.net);
      setText('header-rate-'+resource,(net>=0 ? '+' : '')+net.toFixed(1)+'/h · scav +'+scavenged[resource].toFixed(1)+'/h');
      const note=document.getElementById('header-rate-'+resource);
      if (note) note.title='Net rate before storage limits; scavenging is gross recovery. Full storage can discard supplies. Paused net rates describe the plan when resumed.';
    }
    const yieldText=(values,hourly=false)=>Object.entries(values).filter(([,v])=>v>0)
      .map(([r,v])=>Number(v).toFixed(1)+' '+r+(hourly ? '/h' : '')).join(' · ') ||
      (hourly ? 'No current yield' : 'Nothing recovered yet');
    for (const site of state.scavenging || []) {
      setText('scavenge-workers-'+site.job_id,site.workers);
      setText('scavenge-yield-'+site.job_id,yieldText(site.rates,true));
      setText('scavenge-recovered-'+site.job_id,yieldText(site.recovered));
      if (typeof site.remaining_salvage === 'string') setText('derelict-salvage-'+site.site_id,site.remaining_salvage);
      setText('scavenge-eta-'+site.job_id,site.eta);
      setText('scavenge-percent-'+site.job_id,Math.round(site.percent)+'% recovered');
      const progress=document.getElementById('scavenge-progress-'+site.job_id);
      if (progress) progress.value=site.percent;
    }
    for (const resource of ['food', 'water']) {
      document.getElementById(`amount-${resource}`).textContent = state[resource].toFixed(2);
      const hours = state.rates[resource].hours_to_empty;
      document.getElementById(`remaining-${resource}`).textContent =
        hours === null ? 'Stable' : `${hours.toFixed(1)} hours`;
    }
    for (const [resource,amount] of Object.entries(state.materials || {})) {
      const element=document.getElementById(`amount-${resource}`);
      if(element) element.textContent=amount.toFixed(2);
    }
    for (const [resource,amount] of Object.entries(state.trade_available || {})) {
      const usable=document.getElementById(`trade-available-${resource}`);
      const held=document.getElementById(`trade-reserved-${resource}`);
      if(usable) usable.textContent=amount.toFixed(2);
      if(held) held.textContent=(state.trade_reserved[resource] || 0).toFixed(2);
    }
    window.dispatchEvent(new CustomEvent('build-resources', {detail:state.trade_available || state.materials || {}}));
    window.dispatchEvent(new CustomEvent('storage-status', {detail:state.storage_status || {}}));
    if(state.citizen_portal)window.dispatchEvent(new CustomEvent('citizen-portal',{detail:state.citizen_portal}));
    if(state.military_portal)window.dispatchEvent(new CustomEvent('military-portal',{detail:state.military_portal}));
    if(state.operation_results)window.dispatchEvent(new CustomEvent('operation-results',{detail:state.operation_results}));
    for(const [resource,row] of Object.entries(state.storage_status || {})) {
      const cap=document.getElementById('storage-capacity-'+resource);
      if(cap){cap.textContent=['scrap','metal','electronics'].includes(resource)?Number(row.used).toFixed(1)+' / '+row.capacity+' shared':' / '+row.capacity;cap.title=row.description;}
    }

    for (const [id,seconds] of Object.entries(state.raid_timers || {})) {
      const timer=document.getElementById(`raid-timer-${id}`);
      if(timer) timer.textContent=seconds;
    }
    for (const [id,seconds] of Object.entries(state.war_timers || {})) {
      const timer=document.getElementById(`war-timer-${id}`);
      if(timer) timer.textContent=seconds;
    }
    const overall = document.getElementById('overall-score');
    if (overall && state.own_score !== undefined) overall.textContent = state.own_score.toFixed(2);
    for (const score of state.scores || []) {
      if (Number.isFinite(score.processed_at)) setText('score-clock-'+score.settlement_id,new Date(score.processed_at*1000).toISOString().replace('T',' ').slice(0,19));
      for (const category of ['overall', 'population', 'military', 'wealth', 'development']) {
        const cell = document.getElementById(`score-${score.settlement_id}-${category}`);
        if (cell) cell.textContent = score[category].toFixed(2);
      }
    }
    connectionStatus.textContent = 'Supplies are up to date.';
  } catch (error) {
    connectionStatus.textContent = 'Could not refresh values. Retrying automatically; your save is retained.';
  } finally {
    window.setTimeout(refreshSupplies, 5000);
  }
}

window.setTimeout(refreshSupplies, 5000);
