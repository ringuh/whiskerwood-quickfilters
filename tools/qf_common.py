"""Shared helpers for the QuickFilters generator (on top of t3d.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from t3d import *
import t3d

MOD = 'QuickFilters'
CFG = 'QuickFiltersConfig'
M = '/Game/Mods/%s/' % MOD
KSL = '/Script/Engine.KismetSystemLibrary'
KML = '/Script/Engine.KismetMathLibrary'
KSTR = '/Script/Engine.KismetStringLibrary'
KTXT = '/Script/Engine.KismetTextLibrary'
KAL = '/Script/Engine.KismetArrayLibrary'
API = '/Script/SystemCore.ModAPI'
PA = '/Script/ProjectArco.'
UW = '/Script/UMG.UserWidget'
UWT = OBJ(UW)
WIDGET_T = OBJ('/Script/UMG.Widget')
PANEL = '/Script/UMG.PanelWidget'
TXT_T = OBJ('/Script/UMG.TextBlock')
BTN_T = OBJ('/Script/UMG.Button')
V2 = STRUCT('/Script/CoreUObject.Vector2D')
ACTOR = OBJ('/Script/Engine.Actor')


def wbp_cls(asset):
    return "/Script/UMG.WidgetBlueprintGeneratedClass'%s.%s_C'" % (asset, asset.split('/')[-1])


def wbp_t(asset):
    return T('object', obj=wbp_cls(asset))


# ---- extra pin-type support: delegate member refs + Map value types
_orig_fmt = Pin.fmt
def _fmt(self):
    s = _orig_fmt(self)
    mr = getattr(self, 'memref', None)
    if mr: s = s.replace('PinType.PinSubCategoryMemberReference=()', 'PinType.PinSubCategoryMemberReference=(%s)' % mr, 1)
    v = self.t.get('val')
    if v:
        s = s.replace('PinType.PinValueType=()',
                      'PinType.PinValueType=(TerminalCategory="%s",TerminalSubCategory="%s",TerminalSubCategoryObject=%s,'
                      'bTerminalIsConst=False,bTerminalIsWeakPointer=False,bTerminalIsUObjectWrapper=False)'
                      % (v['cat'], v['sub'], ('"%s"' % v['obj']) if v['obj'] else 'None'), 1)
    return s
Pin.fmt = _fmt


def MAP(kt, vt):
    d = dict(kt); d['cont'] = 'Map'; d['val'] = dict(vt); return d


_orig_prop_type = t3d.prop_type
def prop_type2(p):
    if p['type'] == 'MapProperty':
        return MAP(prop_type2(p['key_prop']), prop_type2(p['value_prop']))
    return _orig_prop_type(p)
t3d.prop_type = prop_type2
prop_type = prop_type2


def modapi(g, x, y, name='Api'):
    return g.call(API + ':GetModAPI', name, x, y)


def api_call(g, fn, x, y, name=None, **kw):
    a = modapi(g, x - 250, y + 150, name=(name or fn) + 'Api')
    n = g.call(API + ':' + fn, name or fn, x, y, **kw)
    link(a['ReturnValue'], n['self'])
    return n


class Gate(Node):
    def __init__(self, entry, exit_):
        self._e, self._x = entry, exit_; self.name = entry.node.name
    def __getitem__(self, k):
        return {'execute': self._e, 'then': self._x}[k]


def knot(g, x, y, name):
    k = g.add(BG + 'K2Node_Knot', name, [], x, y)
    k.pin('InputPin', EXEC); k.pin('OutputPin', EXEC, out=True)
    k.__class__ = _Knot
    return k


class _Knot(Node):
    def __getitem__(self, key):
        return Node.__getitem__(self, {'execute': 'InputPin', 'then': 'OutputPin'}.get(key, key))


def log(g, x, y, msg_pin=None, msg=None, name='Log', trace=False):
    """Debug-only log line (Debug = QuickFiltersConfig\\debug.txt has text), joined back by a reroute knot.
    trace=True: ungated (only for TRACE lines, removed before release)."""
    n = api_call(g, 'LogMessage', x, y, name=name, doPrependDate='true')
    if msg_pin: link(msg_pin, n['Msg'])
    elif msg: n.set('Msg', msg)
    if trace:
        return n
    dg = g.get('Debug', BOOL, x - 200, y + 120, name=name + 'DebugGet')
    br = g.branch(x - 150, y, name + 'IfDebug'); link(dg['Debug'], br['Condition'])
    ex(br, n)
    k = knot(g, x + 250, y - 40, name + 'Join')
    link(n['then'], k['InputPin']); link(br['else'], k['InputPin'])
    return Gate(br['execute'], k['OutputPin'])


def concat(g, x, y, *parts):
    cur = None
    for i, p in enumerate(parts):
        if cur is None:
            if isinstance(p, str):
                c = g.call(KSTR + ':Concat_StrStr', 'Cat', x, y); c.set('A', p); cur = c['ReturnValue']; continue
            cur = p; continue
        c = g.call(KSTR + ':Concat_StrStr', 'Cat', x + 40 * i, y + 30 * i)
        link(cur, c['A'])
        if isinstance(p, str): c.set('B', p)
        else: link(p, c['B'])
        cur = c['ReturnValue']
    return cur


def conv(g, fn, pin, x, y, name, cls=KSTR):
    n = g.call(cls + ':' + fn, name, x, y)
    inp = [p for p in n.pins if not p.out and p.name != 'self' and not p.hidden][0]
    link(pin, inp); return n['ReturnValue']


def istr(g, pin, x, y, name): return conv(g, 'Conv_IntToString', pin, x, y, name)
def bstr(g, pin, x, y, name): return conv(g, 'Conv_BoolToString', pin, x, y, name)
def nstr(g, pin, x, y, name): return conv(g, 'Conv_NameToString', pin, x, y, name)
def lower(g, pin, x, y, name): return conv(g, 'ToLower', pin, x, y, name)


def clean(g, pin, x, y, name):
    """Trim both ends (BP Trim = leading only) and lower case"""
    a = conv(g, 'Trim', pin, x, y, name + 'L')
    b = conv(g, 'TrimTrailing', a, x + 150, y, name + 'R')
    return lower(g, b, x + 300, y, name)


def is_valid(g, pin, x, y, name='Valid'):
    n = g.call(KSL + ':IsValid', name, x, y); link(pin, n['Object']); return n['ReturnValue']


def notb(g, pin, x, y, name):
    n = g.call(KML + ':Not_PreBool', name, x, y); link(pin, n['A']); return n['ReturnValue']


def andb(g, a, b, x, y, name):
    n = g.call(KML + ':BooleanAND', name, x, y); link(a, n['A']); link(b, n['B']); return n['ReturnValue']


def orb(g, a, b, x, y, name):
    n = g.call(KML + ':BooleanOR', name, x, y); link(a, n['A']); link(b, n['B']); return n['ReturnValue']


def streq(g, a, b, x, y, name):
    n = g.call(KSTR + ':EqualEqual_StrStr', name, x, y)
    link(a, n['A']) if not isinstance(a, str) else n.set('A', a)
    link(b, n['B']) if not isinstance(b, str) else n.set('B', b)
    return n['ReturnValue']


def starts(g, pin, prefix, x, y, name):
    n = g.call(KSTR + ':StartsWith', name, x, y, InPrefix=prefix); link(pin, n['SourceString']); return n['ReturnValue']


def struct_node(g, kind, spath, show, x, y, name):
    props = J()[spath]['properties']
    n = g.add(BG + 'K2Node_%sStruct' % kind, name,
              ['StructType="/Script/CoreUObject.ScriptStruct\'%s\'"' % spath, 'bMadeAfterOverridePinRemoval=True'], x, y)
    for i, p in enumerate(props):
        n.header.append('ShowPinForProperties(%d)=(PropertyName="%s",bShowPin=%s,bCanToggleVisibility=True)' % (i, p['name'], p['name'] in show))
    sname = spath.split('.')[-1]
    if kind == 'Break':
        n.pin(sname, STRUCT(spath))
    for p in props:
        if p['name'] in show:
            d = None
            if kind == 'Make':
                d = {'IntProperty': '0', 'StrProperty': '', 'BoolProperty': 'false', 'NameProperty': 'None', 'FloatProperty': '0.0'}.get(p['type'])
            n.pin(p['name'], prop_type(p), out=(kind == 'Break'), default=d)
    if kind == 'Make':
        n.pin(sname, STRUCT(spath), out=True)
    return n


def bind(g, owner_asset, target_pin, owner, delegate, sig_parent, sig, event_node, x, y, name, target_t=None):
    """K2Node_AddDelegate. owner: native class path or a BP class ref string (then target_t must be given).
    sig_parent: MemberParent for the signature, e.g. /Script/CoreUObject.Package'/Script/UMG'."""
    mp = owner if "'" in owner else cls_ref(owner)   # BP class refs are already wrapped
    n = g.add(BG + 'K2Node_AddDelegate', name, ['DelegateReference=(MemberParent="%s",MemberName="%s")' % (mp, delegate)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', target_t or (OBJ(owner) if "'" not in owner else T('object', obj=owner)), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    d = n.pin('Delegate', T('delegate'))
    d.memref = 'MemberParent="%s",MemberName="%s"' % (sig_parent, sig)
    link(target_pin, n['self'])
    ev = event_node['OutputDelegate']
    ev.memref = 'MemberParent="/Script/Engine.BlueprintGeneratedClass\'%s.%s_C\'",MemberName="%s"' % (owner_asset, owner_asset.split('/')[-1], event_node.name)
    link(ev, d)
    return n


PKG = lambda p: "/Script/CoreUObject.Package'%s'" % p


def self_node(g, x, y, name):
    n = g.add(BG + 'K2Node_Self', name, [], x, y)
    n.pin('self', T('object', sub='self'), out=True)
    return n


def arrfn(g, fn, elem_t, x, y, name, arr_pin=None, item_pin=None, item=None, idx_pin=None):
    """KismetArrayLibrary wildcard call with explicit element type."""
    o = J()[KAL + ':' + fn]
    pure = 'FUNC_BlueprintPure' in o['function_flags']
    hdr = []
    if pure: hdr.append('bDefaultsToPureFunc=True')
    hdr.append('FunctionReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(KAL), fn))
    n = g.add(BG + 'K2Node_CallArrayFunction', name, hdr, x, y)
    if not pure: n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', OBJ(KAL), defobj='/Script/Engine.Default__KismetArrayLibrary', hidden=True, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    for p in o['properties']:
        fl = p['flags']; nm_ = p['name']
        ret = 'CPF_ReturnParm' in fl
        if nm_ == 'TargetArray':
            t = ARR(elem_t); t['ref'] = True
            if 'CPF_ConstParm' in fl: t['const'] = True
            n.pin(nm_, t)
        elif nm_ in ('NewItem', 'ItemToFind', 'Item') and not ret:
            t = dict(elem_t)
            outp = 'CPF_OutParm' in fl and 'CPF_ReferenceParm' not in fl and 'CPF_ConstParm' not in fl
            if not outp: t['ref'] = True; t['const'] = True
            n.pin(nm_, t, out=outp)
        else:
            t = prop_type(p)
            d = None if ret else ('0' if t['cat'] == 'int' else 'false' if t['cat'] == 'bool' else None)
            n.pin(nm_, t, out=ret, default=d)
    if arr_pin is not None: link(arr_pin, n['TargetArray'])
    it = 'NewItem' if fn in ('Array_Add', 'Array_AddUnique') else 'ItemToFind' if fn in ('Array_Find', 'Array_Contains') else 'Item'
    if item_pin is not None: link(item_pin, n[it])
    if item is not None: n[it].default = item
    if idx_pin is not None:
        link(idx_pin, n['IndexToRemove' if fn == 'Array_Remove' else 'Index'])
    return n


def item_at(g, arr_pin, elem_t, idx_pin, x, y, name):
    n = g.add(BG + 'K2Node_GetArrayItem', name, ['bReturnByRefDesired=False'], x, y)
    at = ARR(elem_t); at['ref'] = True; at['const'] = True
    n.pin('Array', at); n.pin('Dimension 1', INT, default='0'); n.pin('Output', elem_t, out=True)
    link(arr_pin, n['Array']); link(idx_pin, n['Dimension 1'])
    return n['Output']


def foreach(g, arr_pin, elem_t, x, y, name):
    lp = g.macro('ForEachLoop', elem_t, x, y, name=name); link(arr_pin, lp['Array']); return lp


def bp_get(g, cls, var, t, target_pin, x, y, name):
    n = g.add(BG + 'K2Node_VariableGet', name, ['VariableReference=(MemberParent="%s",MemberName="%s")' % (cls, var)], x, y)
    n.pin(var, t, out=True)
    n.pin('self', T('object', obj=cls), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    link(target_pin, n['self'])
    return n


def bp_call(g, cls, fn, target_pin, x, y, name):
    n = g.add(BG + 'K2Node_CallFunction', name, ['FunctionReference=(MemberParent="%s",MemberName="%s")' % (cls, fn)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', T('object', obj=cls), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    link(target_pin, n['self'])
    return n


def nm(g, pin, x, y, name):
    n = g.call(KSL + ':GetDisplayName', name, x, y); link(pin, n['Object']); return n['ReturnValue']


def clsname(g, pin, x, y, name):
    c = g.call('/Script/Engine.GameplayStatics:GetObjectClass', name + 'Cls', x, y); link(pin, c['Object'])
    n = g.call(KSL + ':GetClassDisplayName', name, x + 200, y); link(c['ReturnValue'], n['Class'])
    return n['ReturnValue']


def class_array(g, classes, ref_t, x, y, name):
    elemC = dict(ref_t); elemC['cont'] = 'None'; elemC['ref'] = False; elemC['const'] = False
    mk = g.add(BG + 'K2Node_MakeArray', name, ['NumInputs=%d' % len(classes)], x, y)
    mk.pin('Array', ARR(elemC), out=True)
    for i, c in enumerate(classes):
        mk.pin('[%d]' % i, elemC, defobj=c)
    return mk['Array']


def descendants(g, root_pin, classes, x, y, name):
    fd = g.call('/Script/SystemCore.NaviUi:FindDecendentsOfClasses', name, x, y, ignoreHidden='false')
    link(root_pin, fd['searchRoot'])
    link(class_array(g, classes, fd['candidateClasses'].t, x - 200, y + 200, name + 'Classes'), fd['candidateClasses'])
    fd['ReturnValue'].t = ARR(WIDGET_T)
    return fd


def validate(path):
    import re as _re
    txt = open(path, encoding='utf-8').read()
    names = set(_re.findall(r'Begin Object Class=\S+ Name="([^"]+)"', txt))
    bad = []
    for m in _re.finditer(r'LinkedTo=\(([^)]*)\)', txt):
        for ref in m.group(1).split(','):
            ref = ref.strip()
            if ref and ref.split(' ')[0] not in names: bad.append(ref)
    # every exec input must be linked (except event-like nodes, which have none)
    unlinked = []
    for blk in txt.split('Begin Object ')[1:]:
        name = _re.search(r'Name="([^"]+)"', blk).group(1)
        for pm in _re.finditer(r'CustomProperties Pin \((.*)\)\s*$', blk, _re.M):
            s = pm.group(1)
            if 'PinCategory="exec"' in s and 'Direction="EGPD_Output"' not in s and 'LinkedTo=' not in s:
                unlinked.append(name + '.' + _re.search(r'PinName="([^"]+)"', s).group(1))
    # ungated LogMessage (must sit behind an IfDebug branch, except TRACE)
    return len(names), bad, unlinked
