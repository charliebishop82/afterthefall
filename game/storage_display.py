"""Capacity markers independent of whether current production is positive."""
from html import escape


def storage_status(state,rates):
    result={}
    for r in ('food','water'):
        capacity=rates[r]['capacity'];used=state['resources'][r]
        result[r]=dict(full=used>=capacity-1e-8,used=used,capacity=capacity,
                       description=f'{r.title()} storage: {used:g} / {capacity:g}.')
    materials=('scrap','metal','electronics')
    capacity=next((rates[r]['capacity'] for r in materials if r in rates),
                  state['config']['town_hall']['material_storage'])
    used=sum(state['resources'][r] for r in materials)
    for r in materials:
        result[r]=dict(full=used>=capacity-1e-8,used=used,capacity=capacity,
                       description=f'Shared Scrap, Metal and Electronics storage: {used:g} / {capacity:g}.')
    return result


def badge(resource,status):
    return (f'<a id="storage-full-{resource}" class="storage-full" href="#construction" '
            f'aria-label="Storage full. {escape(status["description"],quote=True)}" '
            f'title="{escape(status["description"],quote=True)} Add storage, use supplies or sell surplus."'
            +('' if status['full'] else ' hidden')+'>Full</a>')


def capacity_label(resource,status):
    shared=resource in ('scrap','metal','electronics')
    return (f'<span id="storage-capacity-{resource}" class="resource-capacity" '
            f'title="{escape(status["description"],quote=True)}">'
            +(f'{status["used"]:g} / {status["capacity"]:g}' if shared else f' / {status["capacity"]:g}')
            +(' shared' if shared else '')+'</span>')
