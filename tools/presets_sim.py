"""Python mirror of BP_MapLoad's config parser + preset expansion (same string ops as the graph)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
def bp_trim(s): return s.lstrip()          # KismetStringLibrary Trim = leading only
def clean(s): return bp_trim(s).rstrip().lower()

def parse(defaults_text, user_text):
    lines = [l for l in (defaults_text + '|' + user_text.replace('\n', '|')).split('|') if l != '']
    names, items, section = [], [], ''
    for raw_line in lines:
        raw_line = raw_line.split(';', 1)[0].split('#', 1)[0]
        L = clean(raw_line)
        if L == '' or L.startswith(';') or L.startswith('#'): continue
        if L.startswith('['): section = L; continue
        if section != '[presets]': continue
        t = bp_trim(raw_line)
        if '=' not in t: continue
        left, right = t.split('=', 1)
        name, val = left.rstrip(), clean(right)
        if name == '': continue
        idx = next((i for i, n in enumerate(names) if n.lower() == name.lower()), -1)   # FString == ignores case
        if idx >= 0:
            if val == '': del names[idx]; del items[idx]
            else: items[idx] = val
        elif val != '':
            names.append(name); items.append(val)
    return names, items

def expand(value, item_names, item_cats):
    turn_on = not value.startswith('-')
    if not turn_on: value = value[1:]
    want = []
    for tok in [t for t in value.split(',') if t != '']:
        t = clean(tok)
        if t == '*': want = list(item_names)
        elif t.startswith('@'):
            for n, c in zip(item_names, item_cats):
                if c.lower() == t[1:] and n not in want: want.append(n)
        elif t in [n.lower() for n in item_names]:
            n = [n for n in item_names if n.lower() == t][0]
            if n not in want: want.append(n)
    return want, turn_on

if __name__ == '__main__':
    from quickfilters_build_defaults import DEFAULTS_TEXT
    user = "Stone + ore  = stone, @ore, coal    ; same name\r\nAll food     =                      ; removes it\r\n; my filters\r\n[presets]\r\nStone + ore = stone, @ore, coal\r\n  all FOOD =\r\nFuel = fuel, coal\r\n[other]\r\nx = y\r\n"
    names, items = parse(DEFAULTS_TEXT, user)
    for n, i in zip(names, items): print('%-15s %s' % (n, i))
    assert 'All food' not in names and names[-1] == 'Fuel' and items[names.index('Stone + ore')] == 'stone, @ore, coal'
    inames = ['stone', 'wood', 'copperore', 'coal', 'wheat', 'berries']
    icats = ['basic', 'basic', 'ore', 'ore', 'rawFood', 'rawFood']
    print(expand('stone, @ore, coal', inames, icats))
    assert expand('stone, @ore, coal', inames, icats) == (['stone', 'copperore', 'coal'], True)
    assert expand('-*', inames, icats) == (inames, False)
    assert expand('@rawfood, nosuch', inames, icats) == (['wheat', 'berries'], True)
    print('ok')
