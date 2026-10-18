"""Wall-time estimates based on simulation work, excluding capped excess time."""
import math
import time


def duration(seconds):
    value=max(0,math.ceil(seconds))
    hours,remainder=divmod(value,3600);minutes,seconds=divmod(remainder,60)
    if hours:return f'{hours}h {minutes:02}m'
    if minutes:return f'{minutes}m {seconds:02}s'
    return f'{seconds}s'


class Progress:
    def __init__(self,started_at=None):
        self.started_at=time.monotonic() if started_at is None else started_at
        self.previous=None

    def sample(self,rows,at=None):
        at=time.monotonic() if at is None else at
        members=frozenset(r['settlement_id'] for r in rows)
        remaining=sum(r['behind'] for r in rows)
        split=all('simulation_seconds' in r and 'skip_seconds' in r for r in rows)
        work=sum(r['simulation_seconds'] for r in rows) if split else remaining
        skipped=sum(r['skip_seconds'] for r in rows) if split else 0
        rate=None;eta=None;status='measuring'
        if self.previous:
            previous_at,previous_members,previous_work,previous_split=self.previous
            interval=at-previous_at
            if members==previous_members and split==previous_split and interval>0:
                cleared=previous_work-work
                if cleared>0:
                    rate=cleared/interval/60
                    eta=math.ceil(work/(cleared/interval))
                    status='recent_rate'
                else:
                    status='backlog_not_shrinking'
        if split and work==0 and remaining>0:
            status='skip_phase';eta=None
        self.previous=(at,members,work,split)
        return dict(elapsed_seconds=round(max(0,at-self.started_at),1),
                    remaining_game_hours=round(remaining/3600,1),
                    simulation_game_hours=round(work/3600,1),
                    skippable_game_hours=round(skipped/3600,1),
                    estimate_basis='simulation' if split else 'calendar',
                    net_game_hours_per_real_minute=round(rate,2) if rate is not None else None,
                    estimated_remaining_seconds=eta,estimate_status=status)


def message(count,stats):
    rate=stats['net_game_hours_per_real_minute'];eta=stats['estimated_remaining_seconds']
    if stats['estimate_status']=='skip_phase':
        speed='simulation allowance complete; skip/shared-clock work pending'
    elif rate is None:
        speed='speed/ETA measuring' if stats['estimate_status']=='measuring' else 'simulation backlog not shrinking; ETA unavailable'
    else:
        speed=f'{rate:.2f} game-hours simulated/real min; simulation ETA ~{duration(eta)} (recent rate; skip/shared work extra)'
    backlog=(f'{stats["simulation_game_hours"]:.1f}h to simulate; {stats["skippable_game_hours"]:.1f}h to skip'
             if stats['estimate_basis']=='simulation' else f'{stats["remaining_game_hours"]:.1f} combined game-hours behind')
    return (f'Background simulation: elapsed {duration(stats["elapsed_seconds"])}; '
            f'{count} settlements pending; {backlog}; {speed}.')
