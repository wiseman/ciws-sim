"""Analyse a zen_voices.py run: clips heard more than once (and any within the page's no-repeat
window, which only buckets with `repeat: 0` should show), lines by bucket, and what our ship's
launches got."""
import json, sys, collections
d = json.load(open(sys.argv[1])); events = d['log']
heard = [e for e in events if 'name' in e]
c = collections.Counter(e['name'] for e in heard)
print('lines heard:', len(heard))
print('repeats:', {k: v for k, v in c.items() if v > 1})
last, soon = {}, []
for e in heard:
    if e['name'] in last and e['at'] - last[e['name']] < d['repeat']:
        soon.append((e['t'], e['bucket'], e['name']))
    last[e['name']] = e['at']
print(f"within {d['repeat']} s:", soon)
print('buckets:', dict(collections.Counter(e['bucket'] for e in heard)))
print('heard:', [(e['t'], e['name']) for e in heard])
# Our ship's launches: the warning before each (routine or answering a vampire), "Stand by for
# missile launch" within 12 s before it, and "Birds away" within 4 s after
said = lambda name, lo, hi: any(e['name'] == name and lo <= e['at'] <= hi for e in heard)
warns = [e for e in events if e.get('event') == 'warn']
for e in (e for e in events if e.get('event') == 'launch'):
    w = next((w for w in reversed(warns) if e['t'] - 12 <= w['t'] <= e['t']), None)
    kind = 'salvo/unwarned' if w is None else 'routine' if w['routine'] else 'response'
    print(f"launch {e['t']:7.2f} {kind:15s} stand-by: {said('missile-launch', e['t'] - 12, e['t'])}  "
          f"birds away: {said('birds-away', e['t'], e['t'] + 4)}")
print(d['cic'])
