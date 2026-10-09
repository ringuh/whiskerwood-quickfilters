"""Generates the Blueprint paste text (T3D) for the QuickFilters mod into tools/out/.
Usage: JMAP=path/to/Whiskerwood-x.jmap.gz python tools/quickfilters_build.py

Assets (/Game/Mods/QuickFilters/):
  BP_Startup        Actor        mod options
  BP_MapLoad        Actor        all logic (see the BP_MapLoad section)
  WBP_HopperHelper  Widget BP, parent UI_AimBoxDetails (Input Hopper window class)  -> ReadState
  WBP_SorterHelper  Widget BP, parent UI_Sorter (Filter window class)               -> ReadState
  WBP_QuickWaiter   Widget BP, parent UserWidget, empty designer; event dispatcher Done
  WBP_QuickPanel    Widget BP, designer only: the side panel; VerticalBox `List` (Is Variable)
  WBP_QuickButton   Widget BP, designer only: Button `Btn` -> TextBlock `Label` (both Is Variable)
  PAL_QuickFilters  Primary Asset Label, chunk 28

How the game does it (jmap 0.7.207 + exe strings):
  - Input Hopper window = native UI_AimBoxDetails, Filter window = native UI_Sorter (both ArcoView).
  - Their private BP-callable CalcHudState returns AimBoxHudData / SorterHudData:
      stockpileData: Map<Name subcategory, ResourceStockpileSubcategory{Slots: Map<Name resource, slot{whitelisted}>}>
      whitelist: Set<Name>  (+ whitelistEnabled / allowOverflow)
  - An icon click sends the HudAction "toggleFilter" (exe string next to setAssignedDropoffOnly / enableWhitelist).
    We send the same action to the open window's ReceiveHudAction, once per resource whose state must change.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from qf_common import *

BUILD = 'v13'
OUT = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT, exist_ok=True)

STARTUP, MAPLOAD = M + 'BP_Startup', M + 'BP_MapLoad'
HOPH, SORTH = M + 'WBP_HopperHelper', M + 'WBP_SorterHelper'
WAITER, PANELW, QBTN, CATROW = M + 'WBP_QuickWaiter', M + 'WBP_QuickPanel', M + 'WBP_QuickButton', M + 'WBP_CatRow'
HOPV, SORTV, AWB = PA + 'UI_AimBoxDetails', PA + 'UI_Sorter', PA + 'ArcoWidgetBase'
AIMS, SORTS, SUBS = PA + 'AimBoxHudData', PA + 'SorterHudData', PA + 'ResourceStockpileSubcategory'
HUDA = PA + 'HudAction'
OPT_CAT, OPT_PANEL = 'QuickFilters_Categories', 'QuickFilters_Panel'
TOGGLE_ACTION = 'resourceClicked'
CAT_LABEL = 'toggle'
PANEL_W = 230.0     # slate units; panel goes left of the window if there is this much room, else right
GAP_PX = 22.0  # pixels between the panel and the window's icon list (frame edge ~16 px + 6 px space)
GAP = 16.0   # slate units between the panel and the window's scroll list (= the window frame edge)

# Built-in custom filters ([presets] section). The user file QuickFiltersConfig\QuickFilters.txt is read after
# these, same format; a later line with the same name replaces it, "Name =" (empty) removes it.
DEFAULT_PRESETS = [
    ('All', '*'),
    ('Stone + ore', 'stone, @ore'),
    ('All farmed', 'wheat, berries, mushroom, flax, cotton, tealeaves, peppers, wood'),
    ('Base materials', 'wood, stone, @ore, rawfish, wheat, berries, mushroom, flax, cotton, tealeaves, peppers'),
    ('All food', '@rawFood, @foodTier1, @preparedFood, @mealFood'),
    ('Metal bars', 'copperbar, bronze, ironbar, steel, goldbar'),
]
DEFAULTS_TEXT = '|'.join(['[presets]'] + ['%s = %s' % kv for kv in DEFAULT_PRESETS])

STR_A, NAME_A = ARR(STR), ARR(NAME)
CAT_ORDER = 'rawFood,foodTier1,preparedFood,mealFood,tea,raw,ore,refined,tools,naval,trade'   # window order (Filter dump 2026-10-08)
QBTN_CLS, QBTN_T = wbp_cls(QBTN), wbp_t(QBTN)
CATROW_CLS, CATROW_T = wbp_cls(CATROW), wbp_t(CATROW)
PANEL_CLS, PANEL_T = wbp_cls(PANELW), wbp_t(PANELW)
WAITER_CLS, WAITER_T = wbp_cls(WAITER), wbp_t(WAITER)
MAPLOAD_BGC = "/Script/Engine.BlueprintGeneratedClass'%s.%s_C'" % (MAPLOAD, 'BP_MapLoad')


def write(name, g):
    open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8').write(g.text())


def retype(pin, t):
    keep = {k: pin.t[k] for k in ('ref', 'const')}
    pin.t = dict(t); pin.t.update(keep)


# =========================================================================== BP_Startup (Actor)
g = Graph(STARTUP)
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, 0)
prev = bp
for i, (oid, disp, desc) in enumerate([
        (OPT_CAT, 'Quick Filters - category buttons',
         'Adds an "all / none" button to every category in the Input Hopper and Filter windows: turns the whole category on, '
         'or off when all of it is already on.'),
        (OPT_PANEL, 'Quick Filters - custom filter list',
         'Shows your custom filters (e.g. Stone + ore, All farmed) beside the Input Hopper and Filter windows. Clicking one '
         'turns its resources on. Edit them in Saved/mods/QuickFiltersConfig/QuickFilters.txt.')]):
    vals = g.add(BG + 'K2Node_MakeArray', 'Vals%d' % i, ['NumInputs=2'], 300 + 700 * i, 250)
    vals.pin('Array', ARR(STR), out=True)
    vals.pin('[0]', STR, default='On'); vals.pin('[1]', STR, default='Off')
    reg = api_call(g, 'RegisterModOptions', 600 + 700 * i, 0, name='Reg%d' % i,
                   optionId=oid, optionDisplayName=disp, DefaultValue='On', optionDescription=desc)
    link(vals['Array'], reg['Values'])
    ex(prev, reg); prev = reg
write('BP_Startup', g)


# =========================================================================== helpers (parent UI_AimBoxDetails / UI_Sorter)
# Variables (both): Hud (AimBoxHudData / SorterHudData structure), Keys, SlotKeys, Allowed, ItemNames (Name arrays),
#                   Cats, ItemCats (String arrays), WlOn (Boolean)
# ReadState flattens CalcHudState into parallel arrays: ItemNames[i] belongs to category ItemCats[i];
# Cats = categories in window order; Allowed = the whitelist (resources switched on).
def helper(asset, view, hud_s, flag):
    g = Graph(asset)
    HUD_T = STRUCT(hud_s)
    ev = g.custom_event('ReadState', [], 0, 0)
    cs = g.call(view + ':CalcHudState', 'Compute', 250, 200)   # Target empty = self (Context set by BP_MapLoad)
    sh = g.setv('Hud', HUD_T, 500, 0, name='SetHud'); link(cs['ReturnValue'], sh['Hud'])
    if 'execute' in [p.name for p in cs.pins]:
        ex(ev, cs); ex(cs, sh)
    else:
        ex(ev, sh)
    prev = sh
    for i, (var, t) in enumerate([('Cats', STR), ('ItemNames', NAME), ('ItemCats', STR)]):
        c = arrfn(g, 'Array_Clear', t, 750 + 250 * i, 0, 'Clear' + var, arr_pin=g.get(var, ARR(t), 700 + 250 * i, 200, name=var + 'GetC')[var])
        ex(prev, c); prev = c
    hg = g.get('Hud', HUD_T, 1500, 250, name='HudGet')
    bk = struct_node(g, 'Break', hud_s, ['stockpileData', 'whitelist', flag], 1700, 250, 'BreakHud'); link(hg['Hud'], bk[hud_s.split('.')[-1]])
    sa = g.call('/Script/Engine.BlueprintSetLibrary:Set_ToArray', 'WhitelistToArray', 1550, 0)
    retype(sa['A'], SET(NAME)); retype(sa['Result'], NAME_A)
    link(bk['whitelist'], sa['A']); ex(prev, sa)
    sal = g.setv('Allowed', NAME_A, 1800, 0, name='SetAllowed'); link(sa['Result'], sal['Allowed']); ex(sa, sal)
    swl = g.setv('WlOn', BOOL, 2050, 0, name='SetWlOn'); link(bk[flag], swl['WlOn']); ex(sal, swl)
    MAP_T = MAP(NAME, STRUCT(SUBS))
    mk = g.call('/Script/Engine.BlueprintMapLibrary:Map_Keys', 'CategoryKeys', 2300, 0)
    retype(mk['TargetMap'], MAP_T); retype(mk['Keys'], NAME_A)
    link(bk['stockpileData'], mk['TargetMap']); ex(swl, mk)
    sk = g.setv('Keys', NAME_A, 2550, 0, name='SetKeys'); link(mk['Keys'], sk['Keys']); ex(mk, sk)
    lp = foreach(g, g.get('Keys', NAME_A, 2600, 200, name='KeysGet')['Keys'], NAME, 2800, 0, 'CategoryLoop'); ex(sk, lp, 'then', 'Exec')
    K = lp['Array Element']
    mf = g.call('/Script/Engine.BlueprintMapLibrary:Map_Find', 'FindCategory', 3000, 250)
    retype(mf['TargetMap'], MAP_T); retype(mf['Key'], NAME); retype(mf['Value'], STRUCT(SUBS))
    link(bk['stockpileData'], mf['TargetMap']); link(K, mf['Key'])
    bs = struct_node(g, 'Break', SUBS, ['Slots'], 3250, 250, 'BreakCategory'); link(mf['Value'], bs['ResourceStockpileSubcategory'])
    msk = g.call('/Script/Engine.BlueprintMapLibrary:Map_Keys', 'ResourceKeys', 3100, 0)
    retype(msk['TargetMap'], MAP(NAME, STRUCT(PA + 'ResourceStockpileSlot'))); retype(msk['Keys'], NAME_A)
    link(bs['Slots'], msk['TargetMap']); ex(lp, msk, 'LoopBody')
    ssk = g.setv('SlotKeys', NAME_A, 3350, 0, name='SetSlotKeys'); link(msk['Keys'], ssk['SlotKeys']); ex(msk, ssk)
    kraw = nstr(g, K, 3300, 400, 'CatKeyRaw')
    kst = g.call(KSTR + ':Replace', 'CatKeyStr', 3450, 400, From='subcat.', To='', SearchCase='IgnoreCase'); link(kraw, kst['SourceString'])
    kstr = kst['ReturnValue']
    ac = arrfn(g, 'Array_Add', STR, 3600, 0, 'AddCat', arr_pin=g.get('Cats', STR_A, 3550, 200, name='CatsGetA')['Cats'], item_pin=kstr); ex(ssk, ac)
    lp2 = foreach(g, g.get('SlotKeys', NAME_A, 3800, 200, name='SlotKeysGet')['SlotKeys'], NAME, 3850, 0, 'ResourceLoop'); ex(ac, lp2, 'then', 'Exec')
    ai = arrfn(g, 'Array_Add', NAME, 4100, 0, 'AddItem', arr_pin=g.get('ItemNames', NAME_A, 4050, 200, name='ItemNamesGetA')['ItemNames'], item_pin=lp2['Array Element'])
    ex(lp2, ai, 'LoopBody')
    aic = arrfn(g, 'Array_Add', STR, 4350, 0, 'AddItemCat', arr_pin=g.get('ItemCats', STR_A, 4300, 200, name='ItemCatsGetA')['ItemCats'], item_pin=kstr)
    ex(ai, aic)
    return g

write('WBP_HopperHelper', helper(HOPH, HOPV, AIMS, 'whitelistEnabled'))
write('WBP_SorterHelper', helper(SORTH, SORTV, SORTS, 'allowOverflow'))


# =========================================================================== WBP_QuickWaiter (UserWidget, empty designer)
# Variables: Waited (Float), Stage (Integer). Event Dispatcher: Done (no inputs).
# While in the viewport it calls Done on its first tick, at 0.15 s and at 0.45 s (window open animations), then removes itself.
g = Graph(WAITER)
evT = g.event('/Script/UMG.UserWidget', 'Tick', [('MyGeometry', STRUCT('/Script/SlateCore.Geometry')), ('InDeltaTime', FLT)], 'Tick', 0, 0)
wg_ = g.get('Waited', DBL, 0, 250, name='WaitedGet')
add = g.call(KML + ':Add_DoubleDouble', 'AddDelta', 200, 250); link(wg_['Waited'], add['A']); link(evT['InDeltaTime'], add['B'])
sw = g.setv('Waited', DBL, 300, 0, name='SetWaited'); link(add['ReturnValue'], sw['Waited']); ex(evT, sw)
stg = g.get('Stage', INT, 400, 300, name='StageGet')
def call_done(x, y, name):
    n = g.add(BG + 'K2Node_CallDelegate', name, ['DelegateReference=(MemberName="Done",bSelfContext=True)'], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True); n.pin('self', T('object', obj=WAITER_CLS), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    return n
# stage 0: first tick
s0q = g.call(KML + ':EqualEqual_IntInt', 'IsStage0', 600, 300, B='0'); link(stg['Stage'], s0q['A'])
b0 = g.branch(600, 0, 'BrStage0'); link(s0q['ReturnValue'], b0['Condition']); ex(sw, b0)
st1 = g.setv('Stage', INT, 850, -200, value='1', name='ToStage1'); ex(b0, st1)
d0 = call_done(1100, -200, 'CallDoneFirst'); ex(st1, d0)
# stage 1: 0.15 s
s1q = g.call(KML + ':EqualEqual_IntInt', 'IsStage1', 850, 300, B='1'); link(stg['Stage'], s1q['A'])
t1 = g.call(KML + ':GreaterEqual_DoubleDouble', 'After015', 850, 450, B='0.05'); link(sw['Output_Get'], t1['A'])
b1 = g.branch(850, 0, 'BrStage1'); link(andb(g, s1q['ReturnValue'], t1['ReturnValue'], 1050, 350, 'Stage1Due'), b1['Condition']); ex(b0, b1, 'else')
st2 = g.setv('Stage', INT, 1100, 100, value='2', name='ToStage2'); ex(b1, st2)
d1 = call_done(1350, 100, 'CallDoneSecond'); ex(st2, d1)
# stage 2: 0.45 s -> last call, reset, hide
t2 = g.call(KML + ':GreaterEqual_DoubleDouble', 'After045', 1100, 450, B='0.3'); link(sw['Output_Get'], t2['A'])
b2 = g.branch(1100, 300, 'BrDone'); link(t2['ReturnValue'], b2['Condition']); ex(b1, b2, 'else')
r0 = g.setv('Waited', DBL, 1350, 300, value='0.0', name='ResetWaited'); ex(b2, r0)
r1 = g.setv('Stage', INT, 1600, 300, value='0', name='ResetStage'); ex(r0, r1)
rp = g.call('/Script/UMG.Widget:RemoveFromParent', 'Hide', 1850, 300); ex(r1, rp)
d2 = call_done(2100, 300, 'CallDoneLast'); ex(rp, d2)
write('WBP_QuickWaiter', g)


# =========================================================================== BP_MapLoad (Actor)
# Variables: see VARS at the bottom (printed into tools/out/variables.txt).
g = Graph(MAPLOAD)
HH_CLS, HH_T = wbp_cls(HOPH), wbp_t(HOPH)
SH_CLS, SH_T = wbp_cls(SORTH), wbp_t(SORTH)


def gv(var, t, x, y, tag=''):
    return g.get(var, t, x, y, name=var + 'Get' + tag)[var]


def sv(var, t, x, y, val_pin=None, value=None, tag=''):
    n = g.setv(var, t, x, y, value=value, name='Set' + var + tag)
    if val_pin is not None: link(val_pin, n[var])
    return n


def clear(var, t, x, y, tag=''):
    return arrfn(g, 'Array_Clear', t, x, y, 'Clear' + var + tag, arr_pin=gv(var, ARR(t), x - 50, y + 180, 'C' + tag))


def option_on(oid, x, y, tag):
    o = api_call(g, 'ReadModOptionValue', x, y, name='ReadOpt' + tag, optionId=oid, fallbackValue='On')
    return o, streq(g, o['ReturnValue'], 'On', x + 250, y + 200, 'OptOn' + tag)


def label(btn_pin, text_pin, x, y, tag, prev, prev_pin='then'):
    lb = bp_get(g, QBTN_CLS, 'Label', TXT_T, btn_pin, x, y + 200, 'LabelGet' + tag)
    tt = g.call(KTXT + ':Conv_StringToText', 'LabelText' + tag, x, y + 350)
    if isinstance(text_pin, str): tt.set('InString', text_pin)
    else: link(text_pin, tt['InString'])
    st = g.call('/Script/UMG.TextBlock:SetText', 'SetLabel' + tag, x + 250, y); link(lb['Label'], st['self']); link(tt['ReturnValue'], st['InText'])
    ex(prev, st, prev_pin)
    return st


# ---- BeginPlay -> onLoadingFinished (+ setup guard below, for new games)
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, -4000)
api = modapi(g, 200, -3850, name='BindApi')
evL = g.custom_event('OnLoaded', [], 0, -3600)
b1 = bind(g, MAPLOAD, api['ReturnValue'], API, 'onLoadingFinished', PKG('/Script/SystemCore'), 'ModAPI_OnEvent__DelegateSignature', evL, 400, -4000, 'BindLoaded')
ex(bp, b1)

# ---- OnLoaded: Debug, input, helpers, waiter, panel, config
X, Y = 300, -3600
# ---- Setup guard (1.1): a NEW game doesn't deliver onLoadingFinished to BP_MapLoad, so setup also runs from
#      BeginPlay. BeginPlay (after the bind) and OnLoaded enter the same guard: Ready -> nothing; no player
#      controller yet -> SetupTries < 10 -> SetupTries++ -> one-shot 1 s timer back into OnLoaded; else
#      Ready = true -> setup once.
gr = g.branch(-300, -3300, 'BrReady'); link(g.get('Ready', BOOL, -450, -3150, name='ReadyGet')['Ready'], gr['Condition'])
ex(b1, gr); ex(evL, gr)
pcG = g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PCGuard', -300, -3000)
pcv = g.call(KSL + ':IsValid', 'PCGuardValid', -150, -3000); link(pcG['ReturnValue'], pcv['Object'])
gp = g.branch(-50, -3300, 'BrHavePC'); link(pcv['ReturnValue'], gp['Condition']); ex(gr, gp, 'else')
srd = g.setv('Ready', BOOL, 150, -3300, value='true', name='SetReady'); ex(gp, srd)
stg0 = g.get('SetupTries', INT, 0, -2800, name='SetupTriesGet')
stl = g.call(KML + ':Less_IntInt', 'SetupTriesLeft', 150, -2800, B='10'); link(stg0['SetupTries'], stl['A'])
bst = g.branch(150, -3000, 'BrSetupRetry'); link(stl['ReturnValue'], bst['Condition']); ex(gp, bst, 'else')
sta = g.call(KML + ':Add_IntInt', 'SetupTriesPlus', 300, -2850, B='1'); link(stg0['SetupTries'], sta['A'])
sst = g.setv('SetupTries', INT, 400, -3000, name='SetSetupTries'); link(sta['ReturnValue'], sst['SetupTries']); ex(bst, sst)
stm = g.call(KSL + ':K2_SetTimer', 'RetrySetup', 650, -3000, FunctionName='OnLoaded', Time='1.000000', bLooping='false')
link(self_node(g, 500, -2850, 'MeSetupTimer')['self'], stm['Object']); ex(sst, stm)

rdf = api_call(g, 'ReadModTextFile', X, Y, name='ReadDebugFile', modName=CFG, Filename='debug'); ex(srd, rdf)
sdb = sv('Debug', BOOL, X + 300, Y, notb(g, g.call(KSTR + ':IsEmpty', 'DebugFileEmpty', X + 250, Y + 200, )['ReturnValue'], X + 450, Y + 200, 'DebugFileThere'))
link(rdf['ReturnValue'], [n for n in g.nodes if n.name == 'DebugFileEmpty'][0]['InString'])
ex(rdf, sdb)
l0 = log(g, X + 700, Y, msg='QuickFilters ready (%s)' % BUILD, name='LogReady'); ex(sdb, l0)
pc = g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC', X + 900, Y + 250)
ei = g.call('/Script/Engine.Actor:EnableInput', 'EnableKeys', X + 1000, Y)
link(self_node(g, X + 900, Y + 150, 'MeInput')['self'], ei['self']); link(pc['ReturnValue'], ei['PlayerController']); ex(l0, ei)
prev = ei
for i, (asset, var, t) in enumerate([(HOPH, 'HopperHelper', HH_T), (SORTH, 'SorterHelper', SH_T), (PANELW, 'Panel', PANEL_T), (WAITER, 'Waiter', WAITER_T)]):
    cw = g.create_widget(asset, X + 1300 + 500 * i, Y, name='Create' + var); cw['ReturnValue'].t = t
    link(pc['ReturnValue'], cw['OwningPlayer']); ex(prev, cw)
    s = sv(var, t, X + 1550 + 500 * i, Y, cw['ReturnValue']); ex(cw, s); prev = s
# waiter's Done -> OnClickCheck (bound, so the waiter needs no reference to this actor)
evCC = g.custom_event('OnClickCheck', [], 0, -1000)
bw = bind(g, MAPLOAD, gv('Waiter', WAITER_T, X + 3300, Y + 200, 'B'), WAITER_CLS, 'Done',
          WAITER_CLS, 'Done__DelegateSignature', evCC, X + 3400, Y, 'BindWaiterDone', target_t=WAITER_T)
ex(prev, bw)

# config: built-in presets + user file, "|"-joined lines
X, Y = 300, -3000
rcf = api_call(g, 'ReadModTextFile', X, Y, name='ReadConfigFile', modName=CFG, Filename=MOD); ex(bw, rcf)
rep = g.call(KSTR + ':Replace', 'NewlinesToBars', X + 250, Y + 200, From='\\n', To='|'); link(rcf['ReturnValue'], rep['SourceString'])
alltext = concat(g, X + 450, Y + 250, DEFAULTS_TEXT + '|', rep['ReturnValue'])
pia = g.call(KSTR + ':ParseIntoArray', 'SplitLines', X + 700, Y + 200, Delimiter='|', CullEmptyStrings='true'); link(alltext, pia['SourceString'])
sl = sv('Lines', STR_A, X + 300, Y, pia['ReturnValue']); ex(rcf, sl)
ss0 = sv('Section', STR, X + 550, Y, value=''); ex(sl, ss0)
prev = ss0
for i, (var, t) in enumerate([('PresetNames', STR), ('PresetItems', STR), ('PresetButtons', QBTN_T)]):
    c = clear(var, t, X + 800 + 250 * i, Y); ex(prev, c); prev = c
lpL = foreach(g, gv('Lines', STR_A, X + 1500, Y + 200, 'L'), STR, X + 1600, Y, 'LineLoop'); ex(prev, lpL, 'then', 'Exec')
# comments: everything from the first ';' or '#' on a line is ignored (also at the end of a line)
def strip_comment(pin, ch, x, y, tag):
    sp = g.call(KSTR + ':Split', 'CommentSplit' + tag, x, y, InStr=ch, SearchCase='IgnoreCase', SearchDir='FromStart'); link(pin, sp['SourceString'])
    sel = g.call(KML + ':SelectString', 'NoComment' + tag, x + 200, y); link(sp['LeftS'], sel['A']); link(pin, sel['B']); link(sp['ReturnValue'], sel['bPickA'])
    return sel['ReturnValue']
LINE = strip_comment(strip_comment(lpL['Array Element'], ';', X + 1300, Y + 600, 'Semi'), '#', X + 1300, Y + 750, 'Hash')
L = clean(g, LINE, X + 1650, Y + 300, 'LineClean')
skip = orb(g, g.call(KSTR + ':IsEmpty', 'LineEmpty', X + 2100, Y + 400)['ReturnValue'],
           orb(g, starts(g, L, ';', X + 2100, Y + 500, 'IsSemi'), starts(g, L, '#', X + 2100, Y + 600, 'IsHash'), X + 2300, Y + 550, 'IsComment'),
           X + 2500, Y + 450, 'SkipLine')
link(L, [n for n in g.nodes if n.name == 'LineEmpty'][0]['InString'])
bSk = g.branch(X + 1900, Y, 'BrSkipLine'); link(skip, bSk['Condition']); ex(lpL, bSk, 'LoopBody')
bSec = g.branch(X + 2150, Y, 'BrSection'); link(starts(g, L, '[', X + 2150, Y + 700, 'IsSection'), bSec['Condition']); ex(bSk, bSec, 'else')
sSec = sv('Section', STR, X + 2400, Y - 200, L); ex(bSec, sSec)
inP = streq(g, gv('Section', STR, X + 2350, Y + 800, 'P'), '[presets]', X + 2550, Y + 800, 'InPresets')
bInP = g.branch(X + 2400, Y, 'BrInPresets'); link(inP, bInP['Condition']); ex(bSec, bInP, 'else')
# name = value  (original case kept for the name; the value is cleaned when used)
raw = conv(g, 'Trim', LINE, X + 2600, Y + 1000, 'LineTrim')
spl = g.call(KSTR + ':Split', 'SplitEquals', X + 2800, Y + 1000, InStr='=', SearchCase='IgnoreCase', SearchDir='FromStart'); link(raw, spl['SourceString'])
pname = conv(g, 'TrimTrailing', spl['LeftS'], X + 3050, Y + 1000, 'PresetNameT')
pval = clean(g, spl['RightS'], X + 3050, Y + 1100, 'PresetValClean')
okN = andb(g, spl['ReturnValue'], notb(g, g.call(KSTR + ':IsEmpty', 'NameEmpty', X + 3300, Y + 1200)['ReturnValue'], X + 3450, Y + 1200, 'NameThere'),
           X + 3600, Y + 1100, 'ValidPresetLine')
link(pname, [n for n in g.nodes if n.name == 'NameEmpty'][0]['InString'])
bOk = g.branch(X + 2650, Y, 'BrValidLine'); link(okN, bOk['Condition']); ex(bInP, bOk)
fi = arrfn(g, 'Array_Find', STR, X + 2900, Y + 300, 'FindPreset', arr_pin=gv('PresetNames', STR_A, X + 2850, Y + 450, 'F'), item_pin=pname)
sSel = sv('Sel', INT, X + 2900, Y, fi['ReturnValue'], tag='Parse'); ex(bOk, sSel)
have = g.call(KML + ':GreaterEqual_IntInt', 'PresetExists', X + 3150, Y + 300, B='0'); link(sSel['Output_Get'], have['A'])
bHave = g.branch(X + 3150, Y, 'BrPresetExists'); link(have['ReturnValue'], bHave['Condition']); ex(sSel, bHave)
vEmpty = g.call(KSTR + ':IsEmpty', 'ValueEmpty', X + 3400, Y + 300); link(pval, vEmpty['InString'])
# exists: empty value -> remove, else replace
bRm = g.branch(X + 3400, Y - 300, 'BrRemovePreset'); link(vEmpty['ReturnValue'], bRm['Condition']); ex(bHave, bRm)
rm1 = arrfn(g, 'Array_Remove', STR, X + 3650, Y - 450, 'RemoveName', arr_pin=gv('PresetNames', STR_A, X + 3600, Y - 300, 'R'), idx_pin=sSel['Output_Get']); ex(bRm, rm1)
rm2 = arrfn(g, 'Array_Remove', STR, X + 3900, Y - 450, 'RemoveItems', arr_pin=gv('PresetItems', STR_A, X + 3850, Y - 300, 'R'), idx_pin=sSel['Output_Get']); ex(rm1, rm2)
rs1 = arrfn(g, 'Array_Set', STR, X + 3650, Y - 150, 'ReplaceItems', arr_pin=gv('PresetItems', STR_A, X + 3600, Y, 'S'), idx_pin=sSel['Output_Get'], item_pin=pval)
ex(bRm, rs1, 'else')
# new: add (if it has a value)
bAddP = g.branch(X + 3400, Y + 500, 'BrAddPreset'); link(notb(g, vEmpty['ReturnValue'], X + 3400, Y + 700, 'ValueThere'), bAddP['Condition']); ex(bHave, bAddP, 'else')
ad1 = arrfn(g, 'Array_Add', STR, X + 3650, Y + 500, 'AddPresetName', arr_pin=gv('PresetNames', STR_A, X + 3600, Y + 700, 'A'), item_pin=pname); ex(bAddP, ad1)
ad2 = arrfn(g, 'Array_Add', STR, X + 3900, Y + 500, 'AddPresetItems', arr_pin=gv('PresetItems', STR_A, X + 3850, Y + 700, 'A'), item_pin=pval); ex(ad1, ad2)

# after parsing: log, then one button per custom filter in the panel
X, Y = 300, -2200
lC = log(g, X, Y, msg_pin=concat(g, X, Y + 200, 'QuickFilters: config ', istr(g, g.call(KSTR + ':Len', 'UserFileLen', X - 200, Y + 300)['ReturnValue'], X - 50, Y + 300, 'UserLenStr'),
                                 ' chars, custom filters: ', istr(g, arrfn(g, 'Array_Length', STR, X - 200, Y + 400, 'PresetCount', arr_pin=gv('PresetNames', STR_A, X - 300, Y + 450, 'N'))['ReturnValue'], X - 50, Y + 400, 'PresetCountStr'),
                                 ' = ', g.call(KSTR + ':JoinStringArray', 'PresetList', X - 200, Y + 500, Separator=', ')['ReturnValue']), name='LogConfig')
link(rcf['ReturnValue'], [n for n in g.nodes if n.name == 'UserFileLen'][0]['S'])
link(gv('PresetNames', STR_A, X - 400, Y + 550, 'J'), [n for n in g.nodes if n.name == 'PresetList'][0]['SourceArray'])
ex(lpL, lC, 'Completed')
lpB = foreach(g, gv('PresetNames', STR_A, X + 300, Y + 200, 'B'), STR, X + 350, Y, 'PresetButtonLoop'); ex(lC, lpB, 'then', 'Exec')
cqb = g.create_widget(QBTN, X + 650, Y, name='CreatePresetButton'); cqb['ReturnValue'].t = QBTN_T
link(g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC2', X + 500, Y + 250)['ReturnValue'], cqb['OwningPlayer']); ex(lpB, cqb, 'LoopBody')
lb1 = label(cqb['ReturnValue'], lpB['Array Element'], X + 950, Y, 'Preset', cqb)
lst = bp_get(g, PANEL_CLS, 'List', OBJ('/Script/UMG.VerticalBox'), gv('Panel', PANEL_T, X + 1150, Y + 300, 'L'), X + 1300, Y + 300, 'PanelListGet')
acp = g.call(PANEL + ':AddChild', 'AddPresetButton', X + 1450, Y); link(lst['List'], acp['self']); link(cqb['ReturnValue'], acp['Content']); ex(lb1, acp)
csl = g.cast('/Script/UMG.VerticalBoxSlot', False, X + 1700, Y, name='PresetSlot'); link(acp['ReturnValue'], csl['Object']); ex(acp, csl)
spd = g.call('/Script/UMG.VerticalBoxSlot:SetPadding', 'PadPresetButton', X + 1950, Y, InPadding='(Left=0.000000,Top=2.000000,Right=0.000000,Bottom=2.000000)')
link(csl['AsVerticalBoxSlot'], spd['self']); ex(csl, spd)
evPC = g.custom_event('OnPresetClick', [], 0, 3000)
pbtn = bp_get(g, QBTN_CLS, 'Btn', BTN_T, cqb['ReturnValue'], X + 2000, Y + 300, 'PresetBtnGet')
bpc = bind(g, MAPLOAD, pbtn['Btn'], '/Script/UMG.Button', 'OnClicked', PKG('/Script/UMG'), 'OnButtonClickedEvent__DelegateSignature', evPC, X + 2200, Y, 'BindPresetClick')
ex(spd, bpc); ex(csl, bpc, 'CastFailed')
apb = arrfn(g, 'Array_Add', QBTN_T, X + 2450, Y, 'AddPresetButtonRef', arr_pin=gv('PresetButtons', ARR(QBTN_T), X + 2400, Y + 200, 'A'), item_pin=cqb['ReturnValue'])
ex(bpc, apb)
# resource catalog from the game's Resources table (column subCategory): used by windows whose own read has no list
X, Y = 300, -1900
RES_IDS = 'wood,planks,stone,bricks,wheat,flour,spice,rawfish,mushroom,berries,bread,smokedfish,berrysoup,jampastry,stew,fishskewers,simplemeal,heartymeal,platter,cannedfood,basicRations,tea,finetea,tealeaves,flax,cotton,rope,fabric,fishingnet,sail,clothes,bedding,copperore,tinore,ironore,goldore,coal,rocksalt,potash,cobaltore,copperbar,bronze,ironbar,steel,goldbar,ruby,sapphire,emerald,amethyst,amber,obsidian,fuel,fertilizer,tablesalt,salinesolution,oil,medicine,soap,candles,nails,teaset,furniture,cannonframes,bronzecannons,handTool,steelplates,steelcannons,tools,trinkets,waste,peppers,mousetrap,diplomacySeals,pollution,fallow,thread,simpleclothes,advancedRations,vises,scissors,firetongs,ironpots,precisionscales,firstrate,bathed,corpse,guano,stone_cannonball,iron_cannonball,bronze_cannonball,chainshot_cannonball,pirate_protection'
cid = g.call(KSTR + ':ParseIntoArray', 'SplitResourceIds', X, Y + 300, SourceString=RES_IDS, Delimiter=',', CullEmptyStrings='true')
sci = sv('CatIds', STR_A, X + 200, Y, cid['ReturnValue']); ex(lpB, sci, 'Completed')
pc_ = sci
for i_, (var, t_) in enumerate([('CatNames', NAME), ('CatItemCats', STR), ('CatCats', STR)]):
    c_ = clear(var, t_, X + 450 + 250 * i_, Y, 'T'); ex(pc_, c_); pc_ = c_
lpR = foreach(g, gv('CatIds', STR_A, X + 1150, Y + 200, 'L'), STR, X + 1250, Y, 'ResourceIdLoop'); ex(pc_, lpR, 'then', 'Exec')
rid = g.call(KSTR + ':Conv_StringToName', 'ResourceRow', X + 1400, Y + 300); link(lpR['Array Element'], rid['InString'])
rdv = api_call(g, 'ReadDataTableValue', X + 1550, Y, name='ReadSubCategory', datatableName='Resources', ColumnName='subCategory')
link(rid['ReturnValue'], rdv['rowId']); ex(lpR, rdv, 'LoopBody')
scs = g.call(KSTR + ':Replace', 'SubCatNoPrefix', X + 1800, Y + 300, From='subcat.', To='', SearchCase='IgnoreCase'); link(rdv['ReturnValue'], scs['SourceString'])
okc = andb(g, notb(g, g.call(KSTR + ':IsEmpty', 'SubCatEmpty', X + 2000, Y + 400)['ReturnValue'], X + 2150, Y + 400, 'SubCatThere'),
           notb(g, streq(g, scs['ReturnValue'], 'None', X + 2000, Y + 500, 'SubCatNone'), X + 2150, Y + 500, 'SubCatNotNone'), X + 2300, Y + 450, 'SubCatOk')
link(scs['ReturnValue'], [n for n in g.nodes if n.name == 'SubCatEmpty'][0]['InString'])
bOkc = g.branch(X + 1850, Y, 'BrSubCatOk'); link(okc, bOkc['Condition']); ex(rdv, bOkc)
t1 = arrfn(g, 'Array_Add', NAME, X + 2100, Y, 'AddCatalogName', arr_pin=gv('CatNames', NAME_A, X + 2050, Y + 200, 'T'), item_pin=rid['ReturnValue']); ex(bOkc, t1)
t2 = arrfn(g, 'Array_Add', STR, X + 2350, Y, 'AddCatalogItemCat', arr_pin=gv('CatItemCats', STR_A, X + 2300, Y + 200, 'T'), item_pin=scs['ReturnValue']); ex(t1, t2)
t3 = arrfn(g, 'Array_AddUnique', STR, X + 2600, Y, 'AddCatalogCat', arr_pin=gv('CatCats', STR_A, X + 2550, Y + 200, 'T'), item_pin=scs['ReturnValue']); ex(t2, t3)
lCt = log(g, X + 1500, Y - 400, msg_pin=concat(g, X + 1500, Y - 250, 'QuickFilters: catalog from Resources table: ',
          istr(g, arrfn(g, 'Array_Length', NAME, X + 1300, Y - 200, 'CatalogCount', arr_pin=gv('CatNames', NAME_A, X + 1200, Y - 150, 'N'))['ReturnValue'], X + 1400, Y - 200, 'CatalogCountStr'),
          ' resources, categories ', g.call(KSTR + ':JoinStringArray', 'CatalogCatList', X + 1300, Y - 100, Separator=', ')['ReturnValue']), name='LogCatalog')
link(gv('CatCats', STR_A, X + 1100, Y - 50, 'J'), [n for n in g.nodes if n.name == 'CatalogCatList'][0]['SourceArray'])
scO = sv('CatCats', STR_A, X + 1300, Y - 700, g.call(KSTR + ':ParseIntoArray', 'CategoryOrder', X + 1100, Y - 600, SourceString=CAT_ORDER, Delimiter=',', CullEmptyStrings='true')['ReturnValue'], tag='Order')
ex(lpR, scO, 'Completed'); ex(scO, lCt)

# ---- input: any key / mouse button released (works while paused) or a window button -> waiter
kA = g.add(BG + 'K2Node_InputKey', 'KeyAny', ['InputKey=AnyKey', 'bConsumeInput=False', 'bExecuteWhenPaused=True'], 0, -1600)
kA.pin('Pressed', EXEC, out=True); kA.pin('Released', EXEC, out=True); kA.pin('Key', STRUCT('/Script/InputCore.Key'), out=True)
evWB = g.custom_event('OnWindowButton', [], 0, -1400)
jn = knot(g, 250, -1500, 'InputJoin'); link(kA['Released'], jn['InputPin'])
lWB = log(g, 150, -1300, msg='QuickFilters: window button clicked', name='LogWindowButton'); ex(evWB, lWB); link(lWB['then'], jn['InputPin'])
wtg = gv('Waiter', WAITER_T, 300, -1300, 'K')
inv = g.call('/Script/UMG.Widget:IsInViewport', 'WaiterShown', 500, -1300); link(wtg, inv['self'])
bk = g.branch(500, -1500, 'BrWaiterIdle'); link(inv['ReturnValue'], bk['Condition']); link(jn['OutputPin'], bk['execute'])
bwv = g.branch(750, -1500, 'BrWaiterValid'); link(is_valid(g, wtg, 700, -1250, 'WaiterValid'), bwv['Condition']); ex(bk, bwv, 'else')
atv = g.call('/Script/UMG.UserWidget:AddToViewport', 'ShowWaiter', 1000, -1500); link(wtg, atv['self']); ex(bwv, atv)


# ---- reusable sections (generated as copies; calling our own custom events from the same graph pastes badly)
def read_state(prev, prev_pin, x, y, tag):
    """Win.Context -> the right helper -> ReadState -> copy its arrays into ours. Returns the exit knot."""
    cw = g.cast(AWB, False, x, y, name='WinAsArco' + tag); link(gv('Win', UWT, x - 100, y + 200, 'RS' + tag), cw['Object']); ex(prev, cw, prev_pin)
    ctx = g.get('Context', OBJ('/Script/CoreUObject.Object'), x + 200, y + 250, owner=AWB, name='WinContext' + tag); link(cw['AsArcoWidgetBase'], ctx['self'])
    bS = g.branch(x + 250, y, 'BrSorter' + tag); link(gv('IsSorter', BOOL, x + 200, y + 400, 'RS' + tag), bS['Condition']); ex(cw, bS)
    out = knot(g, x + 2600, y, 'StateRead' + tag)
    ex(cw, out, 'CastFailed', 'InputPin')
    for j, (var, cls, t, pin) in enumerate([('SorterHelper', SH_CLS, SH_T, 'then'), ('HopperHelper', HH_CLS, HH_T, 'else')]):
        yy = y + 600 * j - 300
        hp = gv(var, t, x + 400, yy + 250, 'RS' + tag)
        sc = g.call(KSL + ':SetObjectPropertyByName', 'HelperContext' + var[0] + tag, x + 500, yy, PropertyName='Context')
        link(hp, sc['Object']); link(ctx['Context'], sc['Value']); ex(bS, sc, pin)
        rs = bp_call(g, cls, 'ReadState', hp, x + 750, yy, 'ReadState' + var[0] + tag); ex(sc, rs)
        p = rs
        for k, (v2, t2) in enumerate([('Allowed', NAME_A), ('ItemNames', NAME_A), ('ItemCats', STR_A), ('Cats', STR_A), ('WlOn', BOOL)]):
            hv = bp_get(g, cls, v2, t2, hp, x + 950 + 250 * k, yy + 250, 'H%s%s%s' % (v2, var[0], tag))
            s = sv(v2, t2, x + 1000 + 250 * k, yy, hv[v2], tag=var[0] + tag); ex(p, s); p = s
        link(p['then'], out['InputPin'])
    # a window with no resource list (the Filter reads empty through the helper): use the catalog;
    # a hopper with a list: remember it as the catalog (window order, better than the table one)
    n = arrfn(g, 'Array_Length', NAME, x + 2700, y + 300, 'ItemCountRS' + tag, arr_pin=gv('ItemNames', NAME_A, x + 2600, y + 400, 'RSN' + tag))
    has = g.call(KML + ':Greater_IntInt', 'HasItems' + tag, x + 2850, y + 300, B='0'); link(n['ReturnValue'], has['A'])
    bH = g.branch(x + 2800, y, 'BrHasItems' + tag); link(has['ReturnValue'], bH['Condition']); link(out['OutputPin'], bH['execute'])
    fin = knot(g, x + 4200, y, 'StateReady' + tag)
    bHp = g.branch(x + 3050, y - 300, 'BrRememberCatalog' + tag); link(gv('IsSorter', BOOL, x + 2950, y - 100, 'RC' + tag), bHp['Condition']); ex(bH, bHp)
    link(bHp['then'], fin['InputPin'])
    p = bHp; pp = 'else'
    for k, (dst, src, t2) in enumerate([('CatNames', 'ItemNames', NAME_A), ('CatItemCats', 'ItemCats', STR_A), ('CatCats', 'Cats', STR_A)]):
        s_ = sv(dst, t2, x + 3300 + 250 * k, y - 300, gv(src, t2, x + 3250 + 250 * k, y - 100, 'RC' + tag), tag='RC' + tag); ex(p, s_, pp); p = s_; pp = 'then'
    link(p['then'], fin['InputPin'])
    p = bH; pp = 'else'
    for k, (dst, src, t2) in enumerate([('ItemNames', 'CatNames', NAME_A), ('ItemCats', 'CatItemCats', STR_A), ('Cats', 'CatCats', STR_A)]):
        s_ = sv(dst, t2, x + 3050 + 250 * k, y + 300, gv(src, t2, x + 3000 + 250 * k, y + 500, 'UC' + tag), tag='UC' + tag); ex(p, s_, pp); p = s_; pp = 'then'
    lU = log(g, x + 3900, y + 300, msg='QuickFilters:   window read has no resource list, using the catalog', name='LogUseCatalog' + tag); ex(p, lU)
    link(lU['then'], fin['InputPin'])
    return fin


def apply(prev, prev_pin, x, y, tag):
    """For every resource in Want whose state differs from TurnOn: send toggleFilter to the window."""
    c0 = sv('Changed', INT, x, y, value='0', tag=tag); ex(prev, c0, prev_pin)
    cw = g.cast(AWB, False, x + 250, y, name='WinAsArcoA' + tag); link(gv('Win', UWT, x + 150, y + 200, 'A' + tag), cw['Object']); ex(c0, cw)
    lp = foreach(g, gv('Want', NAME_A, x + 450, y + 200, 'A' + tag), NAME, x + 500, y, 'WantLoop' + tag); ex(cw, lp, 'then', 'Exec')
    W = lp['Array Element']
    isOn = arrfn(g, 'Array_Contains', NAME, x + 700, y + 300, 'IsOn' + tag, arr_pin=gv('Allowed', NAME_A, x + 650, y + 450, 'A' + tag), item_pin=W)
    diff = g.call(KML + ':NotEqual_BoolBool', 'NeedsChange' + tag, x + 900, y + 300); link(isOn['ReturnValue'], diff['A']); link(gv('TurnOn', BOOL, x + 750, y + 550, 'A' + tag), diff['B'])
    bD = g.branch(x + 800, y, 'BrNeedsChange' + tag); link(diff['ReturnValue'], bD['Condition']); ex(lp, bD, 'LoopBody')
    mk = struct_node(g, 'Make', HUDA, ['action', 'paramString', 'paramName', 'paramBool'], x + 1000, y + 300, 'MakeToggle' + tag)
    mk['action'].default = TOGGLE_ACTION
    link(W, mk['paramName']); link(nstr(g, W, x + 850, y + 700, 'WantStr' + tag), mk['paramString'])
    link(gv('TurnOn', BOOL, x + 850, y + 800, 'M' + tag), mk['paramBool'])
    rh = g.call(AWB + ':ReceiveHudAction', 'SendToggle' + tag, x + 1300, y); link(cw['AsArcoWidgetBase'], rh['self']); link(mk['HudAction'], rh['action']); ex(bD, rh)
    inc = g.call(KML + ':Add_IntInt', 'ChangedPlus1' + tag, x + 1500, y + 250, B='1'); link(gv('Changed', INT, x + 1400, y + 350, 'I' + tag), inc['A'])
    sc = sv('Changed', INT, x + 1550, y, inc['ReturnValue'], tag='Inc' + tag); ex(rh, sc)
    l1 = log(g, x + 1850, y, msg_pin=concat(g, x + 1800, y + 200, 'QuickFilters:   ', TOGGLE_ACTION, ' ', nstr(g, W, x + 1650, y + 400, 'WantStrL' + tag),
                                             ' -> ', bstr(g, gv('TurnOn', BOOL, x + 1500, y + 500, 'L' + tag), x + 1650, y + 500, 'TurnOnStr' + tag)), name='LogToggle' + tag)
    ex(sc, l1)
    lD = log(g, x + 800, y - 400, msg_pin=concat(g, x + 800, y - 250, 'QuickFilters: ', tag, ' done, changed ', istr(g, gv('Changed', INT, x + 600, y - 200, 'D' + tag), x + 650, y - 150, 'ChangedStr' + tag),
                                                 ' of ', istr(g, arrfn(g, 'Array_Length', NAME, x + 500, y - 100, 'WantCount' + tag, arr_pin=gv('Want', NAME_A, x + 400, y - 50, 'D' + tag))['ReturnValue'], x + 650, y - 50, 'WantCountStr' + tag),
                                                 ', whitelist/overflow flag=', bstr(g, gv('WlOn', BOOL, x + 500, y + 50, 'D' + tag), x + 650, y + 50, 'WlOnStr' + tag)), name='LogApplied' + tag)
    ex(lp, lD, 'Completed')
    lN = log(g, x + 500, y + 900, msg='QuickFilters: the open window is not an ArcoWidgetBase?', name='LogNotArco' + tag); ex(cw, lN, 'CastFailed')
    return lD


def hovered_index(prev, prev_pin, arr_var, x, y, tag):
    """Sel = index of the button in arr_var whose Btn is hovered (the one just clicked), else -1."""
    s0 = sv('Sel', INT, x, y, value='-1', tag='H' + tag); ex(prev, s0, prev_pin)
    lp = foreach(g, gv(arr_var, ARR(QBTN_T), x + 200, y + 200, 'H' + tag), QBTN_T, x + 250, y, 'HoverLoop' + tag); ex(s0, lp, 'then', 'Exec')
    b = bp_get(g, QBTN_CLS, 'Btn', BTN_T, lp['Array Element'], x + 450, y + 250, 'HoverBtn' + tag)
    ih = g.call('/Script/UMG.Widget:IsHovered', 'IsHovered' + tag, x + 650, y + 250); link(b['Btn'], ih['self'])
    bH = g.branch(x + 550, y, 'BrHovered' + tag); link(ih['ReturnValue'], bH['Condition']); ex(lp, bH, 'LoopBody')
    s1 = sv('Sel', INT, x + 800, y, lp['Array Index'], tag='Hit' + tag); ex(bH, s1)
    ok = g.call(KML + ':GreaterEqual_IntInt', 'GotButton' + tag, x + 600, y + 500, B='0'); link(gv('Sel', INT, x + 450, y + 500, 'G' + tag), ok['A'])
    bOk = g.branch(x + 800, y + 400, 'BrGotButton' + tag); link(ok['ReturnValue'], bOk['Condition']); ex(lp, bOk, 'Completed')
    lN = log(g, x + 1050, y + 600, msg='QuickFilters: click, but no hovered button found', name='LogNoHover' + tag); ex(bOk, lN, 'else')
    return bOk


# ---- OnClickCheck: which hopper / filter window is open?
X, Y = 300, -1000
sw0 = sv('Win', UWT, X, Y, value=None, tag='Clear'); ex(evCC, sw0)
prev, ppin = sw0, 'then'
for j, (view, hvar, ht, sorter) in enumerate([(HOPV, 'HopperHelper', HH_T, 'false'), (SORTV, 'SorterHelper', SH_T, 'true')]):
    xx = X + 250 + 1500 * j
    ga = g.call('/Script/UMG.WidgetBlueprintLibrary:GetAllWidgetsOfClass', 'AllWindows' + hvar[0], xx, Y, WidgetClass=view, TopLevelOnly='false')
    ga['FoundWidgets'].t = ARR(UWT)
    link(self_node(g, xx - 100, Y + 200, 'MeWC' + hvar[0])['self'], ga['WorldContextObject']); ex(prev, ga, ppin)
    lp = foreach(g, ga['FoundWidgets'], UWT, xx + 250, Y, 'WindowLoop' + hvar[0]); ex(ga, lp, 'then', 'Exec')
    W = lp['Array Element']
    notH = g.call(KML + ':NotEqual_ObjectObject', 'NotHelper' + hvar[0], xx + 450, Y + 250); link(W, notH['A']); link(gv(hvar, ht, xx + 300, Y + 350, 'W'), notH['B'])
    vis = g.call('/Script/UMG.Widget:IsVisible', 'WinVisible' + hvar[0], xx + 450, Y + 400); link(W, vis['self'])
    bW = g.branch(xx + 500, Y, 'BrIsWindow' + hvar[0]); link(andb(g, notH['ReturnValue'], vis['ReturnValue'], xx + 650, Y + 300, 'VisibleWindow' + hvar[0]), bW['Condition'])
    ex(lp, bW, 'LoopBody')
    s1 = sv('Win', UWT, xx + 750, Y, W, tag=hvar[0]); ex(bW, s1)
    s2 = sv('IsSorter', BOOL, xx + 1000, Y, value=sorter, tag=hvar[0]); ex(s1, s2)
    prev, ppin = lp, 'Completed'

X, Y = 300, -200
wv = is_valid(g, gv('Win', UWT, X, Y + 200, 'V'), X + 150, Y + 200, 'WinValid')
bV = g.branch(X + 200, Y, 'BrWindowOpen'); link(wv, bV['Condition']); ex(prev, bV, ppin)
# no window: hide the panel
pnl = gv('Panel', PANEL_T, X + 300, Y + 700, 'H')
pin_ = g.call('/Script/UMG.Widget:IsInViewport', 'PanelShown', X + 500, Y + 700); link(pnl, pin_['self'])
bPS = g.branch(X + 450, Y + 500, 'BrPanelShown'); link(pin_['ReturnValue'], bPS['Condition']); ex(bV, bPS, 'else')
rpp = g.call('/Script/UMG.Widget:RemoveFromParent', 'HidePanel', X + 700, Y + 500); link(pnl, rpp['self']); ex(bPS, rpp)
# window open: new one?
newW = g.call(KML + ':NotEqual_ObjectObject', 'NewWindow', X + 450, Y + 250); link(gv('Win', UWT, X + 300, Y + 300, 'N'), newW['A']); link(gv('Injected', UWT, X + 300, Y + 400, 'N'), newW['B'])
bN = g.branch(X + 450, Y, 'BrNewWindow'); link(newW['ReturnValue'], bN['Condition']); ex(bV, bN)
posJ = knot(g, X + 9000, Y, 'PositionPanel')


# new window: remember it, read its state, log it
X, Y = 1000, -200
si = sv('Injected', UWT, X, Y, gv('Win', UWT, X - 100, Y + 200, 'I')); ex(bN, si)
sLX = sv('LastX', DBL, X + 50, Y - 450, value='-100000.0', tag='New'); ex(si, sLX)
sCD0 = sv('CatsDone', BOOL, X + 100, Y - 250, value='false', tag='New'); ex(sLX, sCD0)
cB1 = clear('CatButtons', QBTN_T, X + 300, Y - 250, 'New'); ex(sCD0, cB1)
cB2 = clear('CatKeys', STR, X + 550, Y - 250, 'New'); ex(cB1, cB2)
lW = log(g, X + 800, Y - 250, msg_pin=concat(g, X + 250, Y + 200, 'QuickFilters: new window ', nm(g, gv('Win', UWT, X + 50, Y + 300, 'L'), X + 150, Y + 300, 'WinName'),
                                       ' [', clsname(g, gv('Win', UWT, X + 50, Y + 400, 'L2'), X + 150, Y + 400, 'WinClass'), '] sorter=',
                                       bstr(g, gv('IsSorter', BOOL, X + 50, Y + 500, 'L'), X + 150, Y + 500, 'IsSorterStr')), name='LogNewWin')
ex(cB2, lW)
rsN = read_state(lW, 'then', X + 600, Y, 'New')
lS = log(g, X + 3300, Y, msg_pin=concat(g, X + 3250, Y + 200, 'QuickFilters:   categories: ',
                                         g.call(KSTR + ':JoinStringArray', 'CatList', X + 3000, Y + 300, Separator=', ')['ReturnValue'],
                                         ' | resources: ', istr(g, arrfn(g, 'Array_Length', NAME, X + 3000, Y + 400, 'ItemCount', arr_pin=gv('ItemNames', NAME_A, X + 2900, Y + 450, 'N'))['ReturnValue'], X + 3150, Y + 400, 'ItemCountStr'),
                                         ' | on: ', istr(g, arrfn(g, 'Array_Length', NAME, X + 3000, Y + 500, 'OnCount', arr_pin=gv('Allowed', NAME_A, X + 2900, Y + 550, 'N'))['ReturnValue'], X + 3150, Y + 500, 'OnCountStr'),
                                         ' | flag: ', bstr(g, gv('WlOn', BOOL, X + 3000, Y + 600, 'N'), X + 3150, Y + 600, 'WlOnStrN')), name='LogState')
link(gv('Cats', STR_A, X + 2900, Y + 350, 'J'), [n for n in g.nodes if n.name == 'CatList'][0]['SourceArray'])
link(rsN['OutputPin'], lS['execute'])

# bind the window's own buttons (close, toggles, icons) -> OnWindowButton -> re-check shortly after
X, Y = 4800, -200
fdB = descendants(g, gv('Win', UWT, X - 100, Y + 300, 'B'), ['/Script/UMG.Button'], X, Y + 200, 'WindowButtons')
ex(lS, fdB)
lpWB = foreach(g, fdB['ReturnValue'], WIDGET_T, X + 300, Y, 'WindowButtonLoop'); ex(fdB, lpWB, 'then', 'Exec')
cbt = g.cast('/Script/UMG.Button', False, X + 550, Y, name='AsGameButton'); link(lpWB['Array Element'], cbt['Object']); ex(lpWB, cbt, 'LoopBody')
bWB = bind(g, MAPLOAD, cbt['AsButton'], '/Script/UMG.Button', 'OnClicked', PKG('/Script/UMG'), 'OnButtonClickedEvent__DelegateSignature', evWB, X + 800, Y, 'BindWindowButton')
ex(cbt, bWB)

# ---- debug only (first 2 windows): widget tree dump + log every HudAction the window's widgets send
X, Y = 5900, -200
dc = g.call(KML + ':Less_IntInt', 'DumpWanted', X, Y + 300, B='2'); link(gv('DumpCount', INT, X - 150, Y + 300, 'Q'), dc['A'])
bDump = g.branch(X + 100, Y, 'BrDump'); link(andb(g, gv('Debug', BOOL, X, Y + 450, 'Q'), dc['ReturnValue'], X + 200, Y + 400, 'DumpNow'), bDump['Condition'])
ex(lpWB, bDump, 'Completed')
inc = g.call(KML + ':Add_IntInt', 'DumpPlus1', X + 300, Y + 250, B='1'); link(gv('DumpCount', INT, X + 200, Y + 350, 'I'), inc['A'])
sdc = sv('DumpCount', INT, X + 350, Y, inc['ReturnValue']); ex(bDump, sdc)
fdA = descendants(g, gv('Win', UWT, X + 450, Y + 300, 'D'), ['/Script/UMG.TextBlock'], X + 600, Y + 200, 'AllWindowWidgets')
ex(sdc, fdA)
lpD = foreach(g, fdA['ReturnValue'], WIDGET_T, X + 900, Y, 'DumpLoop'); ex(fdA, lpD, 'then', 'Exec')
DW = lpD['Array Element']
par = g.call('/Script/UMG.Widget:GetParent', 'DumpParent', X + 1000, Y + 400); link(DW, par['self'])
ctb = g.cast('/Script/UMG.TextBlock', False, X + 1150, Y, name='DumpAsText'); link(DW, ctb['Object']); ex(lpD, ctb, 'LoopBody')
gtx = g.call('/Script/UMG.TextBlock:GetText', 'DumpGetText', X + 1300, Y + 600); link(ctb['AsTextBlock'], gtx['self'])
tstr = conv(g, 'Conv_TextToString', gtx['ReturnValue'], X + 1450, Y + 600, 'DumpTextStr', cls=KTXT)
msgT = concat(g, X + 1650, Y + 300, 'QuickFilters TREE: ', istr(g, lpD['Array Index'], X + 1300, Y + 300, 'DumpIdx'), ' ', nm(g, DW, X + 1300, Y + 400, 'DumpName'),
              ' [', clsname(g, DW, X + 1300, Y + 500, 'DumpClass'), '] in ', nm(g, par['ReturnValue'], X + 1300, Y + 700, 'DumpParentName'),
              ' [', clsname(g, par['ReturnValue'], X + 1300, Y + 800, 'DumpParentClass'), ']')
lT1 = api_call(g, 'LogMessage', X + 1700, Y - 200, name='LogTreeText', doPrependDate='true'); link(concat(g, X + 1900, Y + 500, msgT, ' text=', tstr), lT1['Msg'])
ex(ctb, lT1)
lT2 = api_call(g, 'LogMessage', X + 1700, Y + 100, name='LogTree', doPrependDate='true'); link(msgT, lT2['Msg']); ex(ctb, lT2, 'CastFailed')
# capture HudActions of every ArcoWidgetBase in the window (+ the window itself)
evHA = g.custom_event('OnSeenHudAction', [('HudAction', STRUCT(HUDA))], 0, 6000)
fdW = descendants(g, gv('Win', UWT, X + 2000, Y + 300, 'H'), ['/Script/UMG.UniformGridPanel'], X + 2100, Y + 200, 'IconGrids')
ex(lpD, fdW, 'Completed')
sGr = sv('Grids', ARR(WIDGET_T), X + 2300, Y, fdW['ReturnValue']); ex(fdW, sGr)
lpG = foreach(g, gv('Grids', ARR(WIDGET_T), X + 2350, Y + 200, 'L'), WIDGET_T, X + 2450, Y, 'GridLoop'); ex(sGr, lpG, 'then', 'Exec')
cgP = g.cast(PANEL, False, X + 2650, Y, name='GridAsPanel'); link(lpG['Array Element'], cgP['Object']); ex(lpG, cgP, 'LoopBody')
gch = g.call(PANEL + ':GetAllChildren', 'GridChildren', X + 2800, Y + 300); link(cgP['AsPanelWidget'], gch['self'])
sIc = sv('Icons', ARR(WIDGET_T), X + 2900, Y, gch['ReturnValue']); ex(cgP, sIc)
lpH = foreach(g, gv('Icons', ARR(WIDGET_T), X + 2950, Y + 200, 'L'), WIDGET_T, X + 3050, Y, 'HudBindLoop'); ex(sIc, lpH, 'then', 'Exec')
caH = g.cast(AWB, False, X + 3300, Y, name='AsArcoForHud'); link(lpH['Array Element'], caH['Object']); ex(lpH, caH, 'LoopBody')
bH = bind(g, MAPLOAD, caH['AsArcoWidgetBase'], AWB, 'OnHudActionDelegate', PKG('/Script/ProjectArco'), 'OnHudAction__DelegateSignature', evHA, X + 3550, Y, 'BindHudSpy')
ex(caH, bH)
caW = g.cast(AWB, False, X + 2650, Y + 500, name='WinAsArcoForHud'); link(gv('Win', UWT, X + 2500, Y + 700, 'HS'), caW['Object']); ex(lpG, caW, 'Completed')
bHW = bind(g, MAPLOAD, caW['AsArcoWidgetBase'], AWB, 'OnHudActionDelegate', PKG('/Script/ProjectArco'), 'OnHudAction__DelegateSignature', evHA, X + 2900, Y + 500, 'BindHudSpyWin')
ex(caW, bHW)
hdJ = knot(g, X + 3200, Y + 800, 'DumpDone'); link(bHW['then'], hdJ['InputPin']); link(caW['CastFailed'], hdJ['InputPin']); ex(bDump, hdJ, 'else')
# the spy event
bkA = struct_node(g, 'Break', HUDA, ['action', 'paramString', 'paramName', 'paramInt', 'paramBool'], 300, 6250, 'BreakSeen')
link(evHA['HudAction'], bkA['HudAction'])
lHA = log(g, 600, 6000, msg_pin=concat(g, 550, 6200, 'QuickFilters SEEN HudAction: action=', bkA['action'], ' paramName=', nstr(g, bkA['paramName'], 450, 6500, 'SeenName'),
                                       ' paramString=', bkA['paramString'], ' paramInt=', istr(g, bkA['paramInt'], 450, 6600, 'SeenInt'),
                                       ' paramBool=', bstr(g, bkA['paramBool'], 450, 6700, 'SeenBool')), name='LogSeen')
ex(evHA, lHA)

# ---- category buttons beside the category headers (option)
X, Y = 9300, -200
# every check (new window or the same one again): fresh state for the hopper's whitelist switch
chk = knot(g, X - 600, Y, 'CheckState'); link(hdJ['OutputPin'], chk['InputPin'])
rsS = read_state(bN, 'else', X - 600, Y + 2500, 'Same'); link(rsS['OutputPin'], chk['InputPin'])
hopOff = andb(g, notb(g, gv('IsSorter', BOOL, X - 500, Y + 300, 'HO'), X - 350, Y + 300, 'IsHopper'),
              notb(g, gv('WlOn', BOOL, X - 500, Y + 400, 'HO'), X - 350, Y + 400, 'WhitelistOff'), X - 200, Y + 350, 'HopperWhitelistOff')
bHO = g.branch(X - 300, Y, 'BrHopperWhitelistOff'); link(hopOff, bHO['Condition']); link(chk['OutputPin'], bHO['execute'])
sCDf = sv('CatsDone', BOOL, X - 50, Y - 400, value='false', tag='Off'); ex(bHO, sCDf)
pnlH = gv('Panel', PANEL_T, X - 50, Y - 200, 'HO')
pinH = g.call('/Script/UMG.Widget:IsInViewport', 'PanelShownHO', X + 150, Y - 200); link(pnlH, pinH['self'])
bPH = g.branch(X + 200, Y - 400, 'BrPanelShownHO'); link(pinH['ReturnValue'], bPH['Condition']); ex(sCDf, bPH)
rpH = g.call('/Script/UMG.Widget:RemoveFromParent', 'HidePanelHO', X + 450, Y - 400); link(pnlH, rpH['self']); ex(bPH, rpH)
lHO = log(g, X + 700, Y - 600, msg='QuickFilters:   hopper whitelist is off: no panel, no category buttons', name='LogHopperOff'); ex(rpH, lHO); link(bPH['else'], lHO['execute'])
bNC = g.branch(X - 50, Y + 100, 'BrNeedCategoryButtons'); link(gv('CatsDone', BOOL, X - 150, Y + 250, 'NC'), bNC['Condition']); ex(bHO, bNC, 'else')
oC, onC = option_on(OPT_CAT, X, Y, 'Cat')
ex(bNC, oC, 'else')
bCo = g.branch(X + 800, Y, 'BrCategoryButtons'); link(onC, bCo['Condition']); ex(oC, bCo)
fdT = descendants(g, gv('Win', UWT, X + 900, Y + 300, 'T'), ['/Script/UMG.TextBlock'], X + 1050, Y + 200, 'WindowTexts')
ex(bCo, fdT)
sTx = sv('Texts', ARR(WIDGET_T), X + 1300, Y, fdT['ReturnValue']); ex(fdT, sTx)
sH0 = sv('HdrIdx', INT, X + 1400, Y - 200, value='0', tag='Reset'); ex(sTx, sH0)
lpT = foreach(g, gv('Texts', ARR(WIDGET_T), X + 1400, Y + 200, 'L'), WIDGET_T, X + 1550, Y, 'HeaderLoop'); ex(sH0, lpT, 'then', 'Exec')
ctx_ = g.cast('/Script/UMG.TextBlock', False, X + 1800, Y, name='HeaderAsText'); link(lpT['Array Element'], ctx_['Object']); ex(lpT, ctx_, 'LoopBody')
gt2 = g.call('/Script/UMG.TextBlock:GetText', 'HeaderGetText', X + 1900, Y + 300); link(ctx_['AsTextBlock'], gt2['self'])
htxt = clean(g, conv(g, 'Conv_TextToString', gt2['ReturnValue'], X + 2050, Y + 300, 'HeaderStr', cls=KTXT), X + 2200, Y + 300, 'HeaderClean')
# headers are matched by position: the n-th "categoryTitle" in the window is category Cats[n]
# (the windows list categories in stockpileData / catalog order; text vs loc comparison didn't match in game)
isCT = streq(g, nm(g, ctx_['AsTextBlock'], X + 1900, Y + 300, 'TitleName'), 'categoryTitle', X + 2100, Y + 300, 'IsCategoryTitle')
bCT = g.branch(X + 2050, Y, 'BrIsCategoryTitle'); link(isCT, bCT['Condition']); ex(ctx_, bCT)
hi = gv('HdrIdx', INT, X + 2100, Y + 450, 'C')
sCur = sv('CurCat', STR, X + 2300, Y, item_at(g, gv('Cats', STR_A, X + 2150, Y + 550, 'C'), STR, hi, X + 2250, Y + 500, 'HeaderCat')); ex(bCT, sCur)
inR = g.call(KML + ':LessEqual_IntInt', 'HeaderInRange', X + 2450, Y + 400); link(hi, inR['A'])
link(arrfn(g, 'Array_Length', STR, X + 2300, Y + 650, 'CatCountH', arr_pin=gv('Cats', STR_A, X + 2200, Y + 700, 'H2'))['ReturnValue'], inR['B'])
hinc = g.call(KML + ':Add_IntInt', 'HdrIdxPlus1', X + 2700, Y + 400, B='1'); link(gv('HdrIdx', INT, X + 2600, Y + 450, 'I'), hinc['A'])
sHi = sv('HdrIdx', INT, X + 2750, Y - 200, hinc['ReturnValue'], tag='Inc'); ex(sCur, sHi)
tpar = g.call('/Script/UMG.Widget:GetParent', 'TitleParent', X + 2600, Y + 1000); link(ctx_['AsTextBlock'], tpar['self'])
wrapped = streq(g, nm(g, tpar['ReturnValue'], X + 2750, Y + 1000, 'TitleParentName'), 'Row', X + 2900, Y + 1000, 'AlreadyWrapped')
bHd = g.branch(X + 2950, Y, 'BrIsHeader'); link(andb(g, inR['ReturnValue'], notb(g, wrapped, X + 3050, Y + 1000, 'NotWrapped'), X + 3150, Y + 900, 'WrapHeader'), bHd['Condition']); ex(sHi, bHd)
CK = gv('CurCat', STR, X + 2600, Y + 800, 'K')
ccb = g.create_widget(QBTN, X + 2650, Y, name='CreateCatButton'); ccb['ReturnValue'].t = QBTN_T
link(g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC3', X + 2500, Y + 250)['ReturnValue'], ccb['OwningPlayer']); ex(bHd, ccb)
lbC = label(ccb['ReturnValue'], CAT_LABEL, X + 2950, Y, 'Cat', ccb)
# restructure the group's VerticalBox: [CategoryTitle, ClickableIcons, ...] -> [Row(CategoryTitle, button), ClickableIcons, ...]
# (UMG has no InsertChildAt / ReplaceChildAt in BP, so: copy children, clear, re-add in order)
hp_ = g.call('/Script/UMG.Widget:GetParent', 'HeaderParent', X + 3100, Y + 300); link(ctx_['AsTextBlock'], hp_['self'])
kids = g.call(PANEL + ':GetAllChildren', 'GroupChildren', X + 3300, Y + 300); link(hp_['ReturnValue'], kids['self'])
sKids = sv('Kids', ARR(WIDGET_T), X + 3250, Y, kids['ReturnValue']); ex(lbC, sKids)
cGB = g.cast(PANEL, False, X + 3350, Y - 250, name='GroupAsPanel'); link(hp_['ReturnValue'], cGB['Object']); ex(sKids, cGB)
sGB = sv('GroupBox', OBJ(PANEL), X + 3500, Y - 250, cGB['AsPanelWidget']); ex(cGB, sGB)
GB = gv('GroupBox', OBJ(PANEL), X + 3700, Y + 500, 'U')
crw = g.create_widget(CATROW, X + 3500, Y, name='CreateCatRow'); crw['ReturnValue'].t = CATROW_T
link(g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC4', X + 3350, Y + 250)['ReturnValue'], crw['OwningPlayer']); ex(sGB, crw)
row = bp_get(g, CATROW_CLS, 'Row', OBJ('/Script/UMG.HorizontalBox'), crw['ReturnValue'], X + 3700, Y + 350, 'CatRowGet')
clr = g.call(PANEL + ':ClearChildren', 'ClearGroup', X + 3800, Y); link(GB, clr['self']); ex(crw, clr)
lpK2 = foreach(g, gv('Kids', ARR(WIDGET_T), X + 3900, Y + 200, 'L'), WIDGET_T, X + 4050, Y, 'GroupChildLoop'); ex(clr, lpK2, 'then', 'Exec')
isT = g.call(KML + ':EqualEqual_ObjectObject', 'IsTitle', X + 4250, Y + 300); link(lpK2['Array Element'], isT['A']); link(ctx_['AsTextBlock'], isT['B'])
bT = g.branch(X + 4300, Y, 'BrIsTitle'); link(isT['ReturnValue'], bT['Condition']); ex(lpK2, bT, 'LoopBody')
re1 = g.call(PANEL + ':AddChild', 'ReAddChild', X + 4550, Y + 300); link(GB, re1['self']); link(lpK2['Array Element'], re1['Content']); ex(bT, re1, 'else')
# the icon grid's new slot would stretch it to full width (big gaps between icons): keep it left-aligned like the game does
cUG = g.cast('/Script/UMG.UniformGridPanel', False, X + 4800, Y + 300, name='ChildIsIconGrid'); link(lpK2['Array Element'], cUG['Object']); ex(re1, cUG)
cVS = g.cast('/Script/UMG.VerticalBoxSlot', False, X + 5050, Y + 300, name='GridSlot'); link(re1['ReturnValue'], cVS['Object']); ex(cUG, cVS)
haG = g.call('/Script/UMG.VerticalBoxSlot:SetHorizontalAlignment', 'GridLeft', X + 5300, Y + 300, InHorizontalAlignment='HAlign_Left'); link(cVS['AsVerticalBoxSlot'], haG['self']); ex(cVS, haG)
ar1 = g.call(PANEL + ':AddChild', 'AddRowToGroup', X + 4550, Y - 300); link(GB, ar1['self']); link(crw['ReturnValue'], ar1['Content']); ex(bT, ar1)
at1 = g.call(PANEL + ':AddChild', 'TitleIntoRow', X + 4800, Y - 300); link(row['Row'], at1['self']); link(lpK2['Array Element'], at1['Content']); ex(ar1, at1)
hs1 = g.cast('/Script/UMG.HorizontalBoxSlot', False, X + 5050, Y - 300, name='TitleSlot'); link(at1['ReturnValue'], hs1['Object']); ex(at1, hs1)
va1 = g.call('/Script/UMG.HorizontalBoxSlot:SetVerticalAlignment', 'TitleVCenter', X + 5300, Y - 300, InVerticalAlignment='VAlign_Center'); link(hs1['AsHorizontalBoxSlot'], va1['self']); ex(hs1, va1)
acc = g.call(PANEL + ':AddChild', 'AddCatButton', X + 5550, Y - 300); link(row['Row'], acc['self']); link(ccb['ReturnValue'], acc['Content']); ex(va1, acc); ex(hs1, acc, 'CastFailed')
hs2 = g.cast('/Script/UMG.HorizontalBoxSlot', False, X + 5800, Y - 300, name='ButtonSlot'); link(acc['ReturnValue'], hs2['Object']); ex(acc, hs2)
va2 = g.call('/Script/UMG.HorizontalBoxSlot:SetVerticalAlignment', 'ButtonVCenter', X + 6050, Y - 300, InVerticalAlignment='VAlign_Center'); link(hs2['AsHorizontalBoxSlot'], va2['self']); ex(hs2, va2)
pd2 = g.call('/Script/UMG.HorizontalBoxSlot:SetPadding', 'ButtonPad', X + 6300, Y - 300, InPadding='(Left=10.000000,Top=2.000000,Right=0.000000,Bottom=0.000000)'); link(hs2['AsHorizontalBoxSlot'], pd2['self']); ex(va2, pd2)
lCA = log(g, X + 4600, Y + 700, msg_pin=concat(g, X + 4550, Y + 900, 'QuickFilters:   category button for ', CK, ' (header ', conv(g, 'Conv_TextToString', gt2['ReturnValue'], X + 4300, Y + 1300, 'HeaderTextL', cls=KTXT), ') added in ', nm(g, GB, X + 4350, Y + 1000, 'HeaderParentName'),
                                         ' [', clsname(g, GB, X + 4350, Y + 1100, 'HeaderParentClass'), '] children ',
                                         istr(g, arrfn(g, 'Array_Length', WIDGET_T, X + 4200, Y + 1200, 'KidCount', arr_pin=gv('Kids', ARR(WIDGET_T), X + 4100, Y + 1250, 'N'))['ReturnValue'], X + 4350, Y + 1200, 'KidCountStr')),
          name='LogCatAdded')
ex(lpK2, lCA, 'Completed')
evCB = g.custom_event('OnCatClick', [], 0, 4500)
cbb = bp_get(g, QBTN_CLS, 'Btn', BTN_T, ccb['ReturnValue'], X + 3800, Y + 300, 'CatBtnGet')
bcc = bind(g, MAPLOAD, cbb['Btn'], '/Script/UMG.Button', 'OnClicked', PKG('/Script/UMG'), 'OnButtonClickedEvent__DelegateSignature', evCB, X + 3900, Y, 'BindCatClick')
ex(lCA, bcc)
a1 = arrfn(g, 'Array_Add', QBTN_T, X + 4150, Y, 'AddCatButtonRef', arr_pin=gv('CatButtons', ARR(QBTN_T), X + 4100, Y + 200, 'A'), item_pin=ccb['ReturnValue']); ex(bcc, a1)
a2 = arrfn(g, 'Array_Add', STR, X + 4400, Y, 'AddCatKey', arr_pin=gv('CatKeys', STR_A, X + 4350, Y + 200, 'A'), item_pin=CK); ex(a1, a2)
lHc = log(g, X + 1800, Y - 400, msg_pin=concat(g, X + 1800, Y - 250, 'QuickFilters:   category buttons added: ',
                                               istr(g, arrfn(g, 'Array_Length', STR, X + 1600, Y - 200, 'CatButtonCount', arr_pin=gv('CatKeys', STR_A, X + 1500, Y - 150, 'N'))['ReturnValue'], X + 1700, Y - 200, 'CatButtonCountStr')),
          name='LogCatButtons')
ex(lpT, lHc, 'Completed')
sCDt = sv('CatsDone', BOOL, X + 2100, Y - 600, value='true', tag='Done'); ex(lHc, sCDt)
link(bCo['else'], posJ['InputPin']); link(sCDt['then'], posJ['InputPin']); link(bNC['then'], posJ['InputPin'])

# ---- position the panel next to the window (option)
X, Y = 9300, 1500
oP, onP = option_on(OPT_PANEL, X, Y, 'Panel')
link(posJ['OutputPin'], oP['execute'])
hasP = g.call(KML + ':Greater_IntInt', 'HasPresets', X + 250, Y + 400, B='0')
link(arrfn(g, 'Array_Length', STR, X + 100, Y + 400, 'PresetCountP', arr_pin=gv('PresetNames', STR_A, X, Y + 450, 'P'))['ReturnValue'], hasP['A'])
bPo = g.branch(X + 300, Y, 'BrShowPanel'); link(andb(g, onP, hasP['ReturnValue'], X + 450, Y + 300, 'ShowPanel'), bPo['Condition']); ex(oP, bPo)
pnl2 = gv('Panel', PANEL_T, X + 400, Y + 600, 'P')
inv2 = g.call('/Script/UMG.Widget:IsInViewport', 'PanelInViewport', X + 600, Y + 600); link(pnl2, inv2['self'])
bIn = g.branch(X + 550, Y, 'BrPanelAdded'); link(inv2['ReturnValue'], bIn['Condition']); ex(bPo, bIn)
atp = g.call('/Script/UMG.UserWidget:AddToViewport', 'ShowPanel', X + 800, Y + 150, ZOrder='50'); link(pnl2, atp['self']); ex(bIn, atp, 'else')
pj = knot(g, X + 1050, Y, 'PanelReady'); link(bIn['then'], pj['InputPin']); link(atp['then'], pj['InputPin'])
fdS = descendants(g, gv('Win', UWT, X + 1000, Y - 100, 'S'), ['/Script/UMG.ScrollBox'], X + 1150, Y - 300, 'WindowScrollBoxes')
link(pj['OutputPin'], fdS['execute'])
gai = g.add(BG + 'K2Node_GetArrayItem', 'FirstScrollBox', ['bReturnByRefDesired=False'], X + 650, Y + 300)
_at = ARR(WIDGET_T); _at['ref'] = True; _at['const'] = True
gai.pin('Array', _at); gai.pin('Dimension 1', INT, default='0'); gai.pin('Output', WIDGET_T, out=True)
link(fdS['ReturnValue'], gai['Array']); sb0 = gai['Output']
gotS = g.call(KML + ':Greater_IntInt', 'HasScrollBox', X + 650, Y + 450, B='0')
link(arrfn(g, 'Array_Length', WIDGET_T, X + 500, Y + 450, 'ScrollBoxCount', arr_pin=fdS['ReturnValue'])['ReturnValue'], gotS['A'])
anchor = g.call(KML + ':SelectObject', 'PlacementAnchor', X + 800, Y + 350); link(sb0, anchor['A']); link(gv('Win', UWT, X + 650, Y + 550, 'G'), anchor['B']); link(gotS['ReturnValue'], anchor['bSelectA'])
caA = g.cast('/Script/UMG.Widget', False, X + 1300, Y - 300, name='AnchorAsWidget'); link(anchor['ReturnValue'], caA['Object']); ex(fdS, caA)
geo = g.call('/Script/UMG.Widget:GetCachedGeometry', 'WinGeometry', X + 900, Y + 400); link(caA['AsWidget'], geo['self'])
me = self_node(g, X + 900, Y + 550, 'MeGeo')['self']
tl = g.call('/Script/UMG.SlateBlueprintLibrary:LocalToViewport', 'WinTopLeft', X + 1150, Y + 400); link(me, tl['WorldContextObject']); link(geo['ReturnValue'], tl['Geometry'])
lsz = g.call('/Script/UMG.SlateBlueprintLibrary:GetLocalSize', 'WinSize', X + 1150, Y + 700); link(geo['ReturnValue'], lsz['Geometry'])
bsz = g.call(KML + ':BreakVector2D', 'WinSizeXY', X + 1350, Y + 700); link(lsz['ReturnValue'], bsz['InVec'])
mtr = g.call(KML + ':MakeVector2D', 'TopRightLocal', X + 1550, Y + 700, Y='0.0'); link(bsz['X'], mtr['X'])
tr = g.call('/Script/UMG.SlateBlueprintLibrary:LocalToViewport', 'WinTopRight', X + 1750, Y + 600); link(me, tr['WorldContextObject']); link(geo['ReturnValue'], tr['Geometry']); link(mtr['ReturnValue'], tr['LocalCoordinate'])
sc_ = g.call('/Script/UMG.WidgetLayoutLibrary:GetViewportScale', 'DpiScale', X + 1350, Y + 900); link(me, sc_['WorldContextObject'])
scd = conv(g, 'Conv_FloatToDouble', sc_['ReturnValue'], X + 1550, Y + 900, 'DpiScaleD', cls=KML)
btl = g.call(KML + ':BreakVector2D', 'TopLeftXY', X + 1400, Y + 400); link(tl['PixelPosition'], btl['InVec'])
btr = g.call(KML + ':BreakVector2D', 'TopRightXY', X + 1950, Y + 600); link(tr['PixelPosition'], btr['InVec'])
need = g.call(KML + ':Multiply_DoubleDouble', 'PanelWidthPx', X + 1750, Y + 900, A='1.0', B=str(PANEL_W * 1.5 + GAP_PX))
roomL = g.call(KML + ':Greater_DoubleDouble', 'RoomOnLeft', X + 1950, Y + 900); link(btl['X'], roomL['A']); link(need['ReturnValue'], roomL['B'])
gap = g.call(KML + ':Multiply_DoubleDouble', 'GapPx', X + 1750, Y + 1050, A='1.0', B=str(GAP_PX))   # fixed pixels (the scale-based gap came out as 0 in game)
# the windows slide in: only place (and show) the panel once the window stopped moving; until then keep it hidden
# and ask the waiter for another look (stops by itself as soon as two looks agree)
same = g.call(KML + ':NearlyEqual_FloatFloat', 'SamePlace', X + 1600, Y - 500, ErrorTolerance='0.5'); link(btl['X'], same['A']); link(gv('LastX', DBL, X + 1450, Y - 450, 'M'), same['B'])
moving = {'ReturnValue': notb(g, same['ReturnValue'], X + 1750, Y - 500, 'StillMoving')}
bMv = g.branch(X + 1500, Y - 700, 'BrWindowMoving'); link(moving['ReturnValue'], bMv['Condition']); ex(caA, bMv)
sLX2 = sv('LastX', DBL, X + 1750, Y - 900, btl['X'], tag='Moving'); ex(bMv, sLX2)
hdM = g.call('/Script/UMG.Widget:RemoveFromParent', 'HidePanelWhileMoving', X + 2000, Y - 900); link(pnl2, hdM['self']); ex(sLX2, hdM)
wtM = gv('Waiter', WAITER_T, X + 2000, Y - 700, 'M')
iwM = g.call('/Script/UMG.Widget:IsInViewport', 'WaiterBusy', X + 2200, Y - 700); link(wtM, iwM['self'])
bWM = g.branch(X + 2250, Y - 900, 'BrWaiterBusyM'); link(iwM['ReturnValue'], bWM['Condition']); ex(hdM, bWM)
awM = g.call('/Script/UMG.UserWidget:AddToViewport', 'LookAgain', X + 2500, Y - 900); link(wtM, awM['self']); ex(bWM, awM, 'else')
bL = g.branch(X + 1300, Y, 'BrRoomLeft'); link(roomL['ReturnValue'], bL['Condition']); ex(bMv, bL, 'else')
# left: panel's top-right corner at the window's top-left
xl = g.call(KML + ':Subtract_DoubleDouble', 'LeftX', X + 2150, Y + 400); link(btl['X'], xl['A']); link(gap['ReturnValue'], xl['B'])
pl = g.call(KML + ':MakeVector2D', 'LeftPos', X + 2350, Y + 400); link(xl['ReturnValue'], pl['X']); link(btl['Y'], pl['Y'])
al = g.call(UW + ':SetAlignmentInViewport', 'AlignRight', X + 1600, Y - 200, Alignment='(X=1.000000,Y=0.000000)'); link(pnl2, al['self']); ex(bL, al)
spl_ = g.call(UW + ':SetPositionInViewport', 'PlaceLeft', X + 1850, Y - 200, bRemoveDPIScale='true'); link(pnl2, spl_['self']); link(pl['ReturnValue'], spl_['position']); ex(al, spl_)
# right: panel's top-left corner at the window's top-right
xr = g.call(KML + ':Add_DoubleDouble', 'RightX', X + 2150, Y + 600); link(btr['X'], xr['A']); link(gap['ReturnValue'], xr['B'])
pr = g.call(KML + ':MakeVector2D', 'RightPos', X + 2350, Y + 600); link(xr['ReturnValue'], pr['X']); link(btr['Y'], pr['Y'])
ar = g.call(UW + ':SetAlignmentInViewport', 'AlignLeft', X + 1600, Y + 100, Alignment='(X=0.000000,Y=0.000000)'); link(pnl2, ar['self']); ex(bL, ar, 'else')
spr = g.call(UW + ':SetPositionInViewport', 'PlaceRight', X + 1850, Y + 100, bRemoveDPIScale='true'); link(pnl2, spr['self']); link(pr['ReturnValue'], spr['position']); ex(ar, spr)
# panel option off but panel shown: hide it
pin3 = g.call('/Script/UMG.Widget:IsInViewport', 'PanelShownOff', X + 600, Y + 1200); link(pnl2, pin3['self'])
bOff = g.branch(X + 550, Y + 1000, 'BrPanelOffShown'); link(pin3['ReturnValue'], bOff['Condition']); ex(bPo, bOff, 'else')
rp3 = g.call('/Script/UMG.Widget:RemoveFromParent', 'HidePanelOff', X + 800, Y + 1000); link(pnl2, rp3['self']); ex(bOff, rp3)
lPos = log(g, X + 2400, Y - 200, msg_pin=concat(g, X + 2400, Y - 50, 'QuickFilters:   panel placed, window at x=',
                                                conv(g, 'Conv_DoubleToString', btl['X'], X + 2200, Y, 'WinXStr'), ' y=',
                                                conv(g, 'Conv_DoubleToString', btl['Y'], X + 2200, Y + 100, 'WinYStr'), ' width px=',
                                                conv(g, 'Conv_DoubleToString', g.call(KML + ':Subtract_DoubleDouble', 'WinWidthPx', X + 2100, Y + 200)['ReturnValue'], X + 2250, Y + 200, 'WinWStr'),
                                                ' left=', bstr(g, roomL['ReturnValue'], X + 2200, Y + 300, 'LeftStr'), ' scale=', conv(g, 'Conv_DoubleToString', scd, X + 2200, Y + 400, 'ScaleStr')), name='LogPlaced')
ww = [n for n in g.nodes if n.name == 'WinWidthPx'][0]; link(btr['X'], ww['A']); link(btl['X'], ww['B'])
link(spl_['then'], lPos['execute']); link(spr['then'], lPos['execute'])

# ---- OnPresetClick: which preset -> Want (+TurnOn) -> apply
X, Y = 300, 3000
hiP = hovered_index(evPC, 'then', 'PresetButtons', X, Y, 'Preset')
rsP = read_state(hiP, 'then', X + 1300, Y, 'Preset')
X = 4300
val = item_at(g, gv('PresetItems', STR_A, X, Y + 300, 'V'), STR, gv('Sel', INT, X, Y + 400, 'V'), X + 200, Y + 300, 'PresetValue')
sVal = sv('Value', STR, X + 200, Y, val); link(rsP['OutputPin'], sVal['execute'])
neg = starts(g, sVal['Output_Get'], '-', X + 400, Y + 300, 'IsNegative')
sTO = sv('TurnOn', BOOL, X + 450, Y, notb(g, neg, X + 550, Y + 300, 'NotNegative'), tag='P'); ex(sVal, sTO)
bNeg = g.branch(X + 700, Y, 'BrNegative'); link(neg, bNeg['Condition']); ex(sTO, bNeg)
chop = g.call(KSTR + ':RightChop', 'DropMinus', X + 800, Y + 300, count='1'); link(gv('Value', STR, X + 650, Y + 400, 'C'), chop['SourceString'])
sVal2 = sv('Value', STR, X + 950, Y - 200, chop['ReturnValue'], tag='Chop'); ex(bNeg, sVal2)
vj = knot(g, X + 1200, Y, 'ValueReady'); link(sVal2['then'], vj['InputPin']); link(bNeg['else'], vj['InputPin'])
cw_ = clear('Want', NAME, X + 1350, Y, 'P'); link(vj['OutputPin'], cw_['execute'])
tok = g.call(KSTR + ':ParseIntoArray', 'SplitTokens', X + 1400, Y + 300, Delimiter=',', CullEmptyStrings='true'); link(gv('Value', STR, X + 1250, Y + 400, 'T'), tok['SourceString'])
sTk = sv('Tokens', STR_A, X + 1600, Y, tok['ReturnValue']); ex(cw_, sTk)
lpK = foreach(g, gv('Tokens', STR_A, X + 1700, Y + 200, 'L'), STR, X + 1850, Y, 'TokenLoop'); ex(sTk, lpK, 'then', 'Exec')
TK = clean(g, lpK['Array Element'], X + 1900, Y + 400, 'TokenClean')
bAll = g.branch(X + 2100, Y, 'BrStar'); link(streq(g, TK, '*', X + 2200, Y + 500, 'IsStar'), bAll['Condition']); ex(lpK, bAll, 'LoopBody')
sWall = sv('Want', NAME_A, X + 2350, Y - 300, gv('ItemNames', NAME_A, X + 2250, Y - 100, 'S'), tag='All'); ex(bAll, sWall)
bAt = g.branch(X + 2350, Y + 100, 'BrCategoryToken'); link(starts(g, TK, '@', X + 2350, Y + 600, 'IsCategoryToken'), bAt['Condition']); ex(bAll, bAt, 'else')
catk = g.call(KSTR + ':RightChop', 'CategoryName', X + 2550, Y + 600, count='1'); link(TK, catk['SourceString'])
lpIC = foreach(g, gv('ItemCats', STR_A, X + 2550, Y + 300, 'P'), STR, X + 2650, Y + 100, 'TokenCatLoop'); ex(bAt, lpIC, 'then', 'Exec')
inCat = streq(g, lower(g, lpIC['Array Element'], X + 2800, Y + 450, 'ItemCatLower'), catk['ReturnValue'], X + 3000, Y + 450, 'InTokenCat')
bIC = g.branch(X + 2900, Y + 100, 'BrInTokenCat'); link(inCat, bIC['Condition']); ex(lpIC, bIC, 'LoopBody')
itn = item_at(g, gv('ItemNames', NAME_A, X + 2900, Y + 600, 'P'), NAME, lpIC['Array Index'], X + 3100, Y + 600, 'TokenCatItem')
au1 = arrfn(g, 'Array_AddUnique', NAME, X + 3150, Y + 100, 'WantCatItem', arr_pin=gv('Want', NAME_A, X + 3100, Y + 300, 'C'), item_pin=itn); ex(bIC, au1)
tn = g.call(KSTR + ':Conv_StringToName', 'TokenName', X + 2600, Y + 900); link(TK, tn['InString'])
known = arrfn(g, 'Array_Find', NAME, X + 2800, Y + 900, 'FindResource', arr_pin=gv('ItemNames', NAME_A, X + 2700, Y + 1050, 'K'), item_pin=tn['ReturnValue'])
kge = g.call(KML + ':GreaterEqual_IntInt', 'KnownResource', X + 3000, Y + 1000, B='0'); link(known['ReturnValue'], kge['A'])
bKn = g.branch(X + 2650, Y + 750, 'BrKnownResource'); link(kge['ReturnValue'], bKn['Condition']); ex(bAt, bKn, 'else')
gameName = item_at(g, gv('ItemNames', NAME_A, X + 2900, Y + 1150, 'KN'), NAME, known['ReturnValue'], X + 3100, Y + 1100, 'GameSpelling')
au2 = arrfn(g, 'Array_AddUnique', NAME, X + 3000, Y + 750, 'WantResource', arr_pin=gv('Want', NAME_A, X + 2950, Y + 950, 'R'), item_pin=gameName); ex(bKn, au2)
lU = log(g, X + 3000, Y + 1200, msg_pin=concat(g, X + 3000, Y + 1350, 'QuickFilters:   not in this window: ', TK), name='LogUnknownToken'); ex(bKn, lU, 'else')
lPs = log(g, X + 2200, Y - 600, msg_pin=concat(g, X + 2200, Y - 450, 'QuickFilters: custom filter ', item_at(g, gv('PresetNames', STR_A, X + 1900, Y - 400, 'LN'), STR, gv('Sel', INT, X + 1900, Y - 300, 'LN'), X + 2050, Y - 400, 'PresetNameL'),
                                                ' = ', gv('Value', STR, X + 2050, Y - 250, 'LV'), ' on=', bstr(g, gv('TurnOn', BOOL, X + 1900, Y - 200, 'LP'), X + 2050, Y - 200, 'TurnOnStrP')), name='LogPreset')
ex(lpK, lPs, 'Completed')
# Value had its '-' chopped already, so remember it in TurnOn: TurnOn false = forced off. Toggle only when TurnOn is true.
bTg = g.branch(X + 2600, Y - 900, 'BrToggleMode'); link(gv('TurnOn', BOOL, X + 2500, Y - 750, 'TG'), bTg['Condition']); ex(lPs, bTg)
sT0p = sv('TurnOn', BOOL, X + 2850, Y - 1100, value='false', tag='PT0'); ex(bTg, sT0p)
lpTw = foreach(g, gv('Want', NAME_A, X + 2950, Y - 900, 'TW'), NAME, X + 3050, Y - 1100, 'ToggleCheckLoop'); ex(sT0p, lpTw, 'then', 'Exec')
onW = arrfn(g, 'Array_Contains', NAME, X + 3200, Y - 850, 'WantItemOn', arr_pin=gv('Allowed', NAME_A, X + 3150, Y - 750, 'TW'), item_pin=lpTw['Array Element'])
bOffW = g.branch(X + 3300, Y - 1100, 'BrWantItemOff'); link(notb(g, onW['ReturnValue'], X + 3400, Y - 850, 'WantItemOff'), bOffW['Condition']); ex(lpTw, bOffW, 'LoopBody')
sT1p = sv('TurnOn', BOOL, X + 3550, Y - 1100, value='true', tag='PT1'); ex(bOffW, sT1p)
ap_in = knot(g, X + 3500, Y - 600, 'ApplyPreset'); link(lpTw['Completed'], ap_in['InputPin']); link(bTg['else'], ap_in['InputPin'])
apply(ap_in, 'then', X + 3600, Y - 600, 'Preset')

# ---- OnCatClick: which category -> Want = its resources, TurnOn = not all on -> apply
X, Y = 300, 4500
hiC = hovered_index(evCB, 'then', 'CatButtons', X, Y, 'Cat')
rsC = read_state(hiC, 'then', X + 1300, Y, 'Cat')
X = 4300
ck = item_at(g, gv('CatKeys', STR_A, X, Y + 300, 'V'), STR, gv('Sel', INT, X, Y + 400, 'C'), X + 200, Y + 300, 'ClickedCat')
sVc = sv('Value', STR, X + 200, Y, ck, tag='Cat'); link(rsC['OutputPin'], sVc['execute'])
cwc = clear('Want', NAME, X + 450, Y, 'C'); ex(sVc, cwc)
sT0 = sv('TurnOn', BOOL, X + 700, Y, value='false', tag='C0'); ex(cwc, sT0)
lpCI = foreach(g, gv('ItemCats', STR_A, X + 850, Y + 200, 'C'), STR, X + 950, Y, 'CatItemLoop'); ex(sT0, lpCI, 'then', 'Exec')
inC = streq(g, lpCI['Array Element'], gv('Value', STR, X + 1000, Y + 450, 'C'), X + 1200, Y + 350, 'InClickedCat')
bInC = g.branch(X + 1200, Y, 'BrInClickedCat'); link(inC, bInC['Condition']); ex(lpCI, bInC, 'LoopBody')
itc = item_at(g, gv('ItemNames', NAME_A, X + 1250, Y + 600, 'C'), NAME, lpCI['Array Index'], X + 1400, Y + 600, 'CatItem')
au3 = arrfn(g, 'Array_AddUnique', NAME, X + 1450, Y, 'WantCatResource', arr_pin=gv('Want', NAME_A, X + 1400, Y + 200, 'CR'), item_pin=itc); ex(bInC, au3)
onI = arrfn(g, 'Array_Contains', NAME, X + 1650, Y + 400, 'CatItemOn', arr_pin=gv('Allowed', NAME_A, X + 1600, Y + 550, 'C'), item_pin=itc)
bOffI = g.branch(X + 1700, Y, 'BrCatItemOff'); link(notb(g, onI['ReturnValue'], X + 1850, Y + 400, 'CatItemOff'), bOffI['Condition']); ex(au3, bOffI)
sT1 = sv('TurnOn', BOOL, X + 1950, Y, value='true', tag='C1'); ex(bOffI, sT1)
lCc = log(g, X + 1200, Y - 500, msg_pin=concat(g, X + 1200, Y - 350, 'QuickFilters: category ', gv('Value', STR, X + 1000, Y - 300, 'CL'), ' clicked, turn on=',
                                                bstr(g, gv('TurnOn', BOOL, X + 1000, Y - 200, 'CL'), X + 1100, Y - 200, 'TurnOnStrC')), name='LogCatClick')
ex(lpCI, lCc, 'Completed')
apply(lCc, 'then', X + 2300, Y - 500, 'Category')

write('BP_MapLoad', g)

# =========================================================================== variables list + validation
VARS = {
    'BP_MapLoad': [
        ('Debug', 'Boolean'), ('Ready', 'Boolean'), ('SetupTries', 'Integer'), ('IsSorter', 'Boolean'), ('WlOn', 'Boolean'), ('TurnOn', 'Boolean'),
        ('Sel', 'Integer'), ('Changed', 'Integer'), ('DumpCount', 'Integer'), ('HdrIdx', 'Integer'), ('CurCat', 'String'),
        ('CatsDone', 'Boolean'), ('GroupBox', 'Panel Widget (Object Reference)'), ('LastX', 'Float'),
        ('Section', 'String'), ('Value', 'String'),
        ('Waiter', 'WBP_QuickWaiter (Object Reference)'), ('Panel', 'WBP_QuickPanel (Object Reference)'),
        ('HopperHelper', 'WBP_HopperHelper (Object Reference)'), ('SorterHelper', 'WBP_SorterHelper (Object Reference)'),
        ('Win', 'User Widget (Object Reference)'), ('Injected', 'User Widget (Object Reference)'),
        ('Lines', 'String **array**'), ('PresetNames', 'String **array**'), ('PresetItems', 'String **array**'),
        ('Tokens', 'String **array**'), ('CatKeys', 'String **array**'), ('Cats', 'String **array**'), ('ItemCats', 'String **array**'),
        ('Allowed', 'Name **array**'), ('ItemNames', 'Name **array**'), ('Want', 'Name **array**'),
        ('PresetButtons', 'WBP_QuickButton (Object Reference) **array**'), ('CatButtons', 'WBP_QuickButton (Object Reference) **array**'),
        ('Texts', 'Widget (Object Reference) **array**'), ('Kids', 'Widget (Object Reference) **array**'),
        ('Grids', 'Widget (Object Reference) **array**'), ('Icons', 'Widget (Object Reference) **array**'),
        ('CatNames', 'Name **array**'), ('CatItemCats', 'String **array**'), ('CatCats', 'String **array**'), ('CatIds', 'String **array**'),
    ],
    'WBP_HopperHelper': [('Hud', 'Aim Box Hud Data (structure)'), ('Keys', 'Name **array**'), ('SlotKeys', 'Name **array**'),
                         ('Allowed', 'Name **array**'), ('ItemNames', 'Name **array**'), ('Cats', 'String **array**'),
                         ('ItemCats', 'String **array**'), ('WlOn', 'Boolean')],
    'WBP_SorterHelper': [('Hud', 'Sorter Hud Data (structure)'), ('Keys', 'Name **array**'), ('SlotKeys', 'Name **array**'),
                         ('Allowed', 'Name **array**'), ('ItemNames', 'Name **array**'), ('Cats', 'String **array**'),
                         ('ItemCats', 'String **array**'), ('WlOn', 'Boolean')],
    'WBP_QuickWaiter': [('Waited', 'Float'), ('Stage', 'Integer'), ('Done', 'Event Dispatcher (no inputs)')],
}
with open(os.path.join(OUT, 'variables.txt'), 'w') as f:
    for k, vs in VARS.items():
        f.write('## %s\n' % k)
        for n_, t_ in vs: f.write('%s\t%s\n' % (n_, t_))

import re as _re
for gname in ('BP_Startup', 'WBP_HopperHelper', 'WBP_SorterHelper', 'WBP_QuickWaiter', 'BP_MapLoad'):
    p = os.path.join(OUT, gname + '.txt')
    n, bad, unl = validate(p)
    txt = open(p, encoding='utf-8').read()
    used = set(_re.findall(r'VariableReference=\(MemberName="([^"]+)",bSelfContext=True\)', txt))
    declared = set(v for v, _ in VARS.get(gname, []))
    missing = sorted(used - declared)
    print('%-18s %4d nodes  %s  unlinked-exec=%s  undeclared-vars=%s' % (gname, n, 'BAD LINKS %s' % bad[:5] if bad else 'links ok', unl[:8], missing))
