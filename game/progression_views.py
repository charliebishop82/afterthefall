"""Read-only citizen XP details from the current season's progression rules."""
from html import escape
import json


def panel(state):
    rules=state['config']['progression'];thresholds=rules['thresholds']
    html='<section class="production-panel" id="citizen-progression" aria-label="Citizen progression" data-xp-thresholds="'+escape(json.dumps(thresholds),quote=True)+'"><h2>Citizen progression</h2>'
    html+=f'<p>Productive work earns {rules["work_xp_per_hour"]:g} XP per equivalent hour; construction, upgrades and repairs earn {rules["construction_xp_per_hour"]:g}. Stalled and idle work earns none. XP is applied on the simulated-minute grid. Levels increase automatically, up to level {len(thresholds)}, improving maximum health and level-based productivity. XP shown here is cumulative.</p>'
    html+='<div class="table-scroll"><table><thead><tr><th>Citizen</th><th>Level</th><th>Total XP</th><th>Next level</th><th>Progress</th></tr></thead><tbody>'
    for c in state['citizens']:
        level=c['level'];xp=c['xp'];maximum=level>=len(thresholds)
        lower=thresholds[min(level-1,len(thresholds)-1)]
        upper=thresholds[level] if not maximum else lower
        span=max(1,upper-lower);earned=max(0,min(span,xp-lower))
        next_text='Maximum level' if maximum else f'{max(0,upper-xp):.2f} XP to level {level+1} ({upper:g} total)'
        html+=f'<tr data-xp-citizen="{c["citizen_id"]}"><th scope="row">{escape(c["name"])} <small>#{c["citizen_id"]}</small></th><td data-xp-level>{level}</td><td data-xp-total>{xp:.2f}</td><td data-xp-next>{next_text}</td><td><progress data-xp-bar max="{span:g}" value="{span if maximum else earned:g}" aria-label="XP progress for {escape(c["name"],quote=True)}"></progress></td></tr>'
    return html+'</tbody></table></div></section>'
