"""App-specific log events layered over the vendored parser.

Contract: parse(line, pet_name=None, group_members=None) -> Optional[dict].
Tries EQL-Assistant-specific regexes FIRST, then falls through to the vendored
parse_line. Never edit vendor/eqlparser to add events.

AA — all three shapes verified against the live log (182 lines, all accounted):
  'You have gained an ability point!  You now have 12 ability points.'   x118
      (double space after '!', singular 'point.' when the balance is 1)
  'You have gained the ability "Ambidexterity" at a cost of 9 ability points.'  x32
      (always 'points', even for costs of 0 and 1)
  'You have improved Combat Fury 2 at a cost of 2 ability points.'       x32
      (rank upgrades; one singular 'point.' occurrence, so tolerate both)
The improved-rank name keeps its trailing rank number ("Combat Fury 2") on
purpose: each rank is a distinct purchase and aa_ledger's PK includes the
ability name, so folding ranks together would drop rows.

Tradeskill depot moves — the vendored parser (v1.6.0) handles the combine
lines ('You have fashioned…', 'You lacked the skills…', 'You can no longer
advance…', 'Consumed N x Item (leaving M) from your personal depot.'); these
two shapes were left to us:
  'You have deposited 20 Kiola Nut to your personal depot.'
  'You have taken 5 Bone Chips from your personal depot.'
plus three fixed-text combine errors (no item names on any of them):
  "Sorry, but you don't have everything you need for this recipe in your general inventory."
  'The result of this combine would produce an unusable item.'
  'You cannot combine these items in this container type!'

Item upgrade merges (336 on the reference log). NO trailing period, and the
result is not always a +N item — spell-rank merges read "Sprouting Heal II":
  'You have successfully merged two items together to create a new item: Platinum Ring +3'
  'You have successfully merged two items together to create a new item: Sprouting Heal II'
"""
import re
from typing import Optional, Set

# RE_TS and _ts are the vendored timestamp matcher and its memo cache; sharing
# them means both parse paths hit one strptime cache instead of two.
from vendor.eqlparser.parser import RE_TS, _ts, parse_line

RE_AA_GAIN = re.compile(
    r'^You have gained an ability point!\s+You now have (\d+) ability points?\.$')
RE_AA_BUY = re.compile(
    r'^You have gained the ability "(.+?)" at a cost of (\d+) ability points?\.$')
RE_AA_IMPROVE = re.compile(
    r'^You have improved (.+?) at a cost of (\d+) ability points?\.$')

RE_DEPOT_DEPOSIT = re.compile(r'^You have deposited (\d+) (.+?) to your personal depot\.$')
RE_DEPOT_TAKE = re.compile(r'^You have taken (\d+) (.+?) from your personal depot\.$')

RE_MERGE = re.compile(
    r'^You have successfully merged two items together to create a new item: (.+?)\.?$')
RE_MERGE_TIER = re.compile(r'\s\+(\d+)$')

CRAFT_ERRORS = {
    "Sorry, but you don't have everything you need for this recipe in your general inventory.":
        'missing_materials',
    'The result of this combine would produce an unusable item.': 'unusable_result',
    'You cannot combine these items in this container type!': 'wrong_container',
}


def _aa(text: str, ts: float) -> Optional[dict]:
    g = RE_AA_GAIN.match(text)
    if g:
        return {'type': 'aa_gain', 'ts': ts, 'points': 1, 'balance_after': int(g.group(1))}
    b = RE_AA_BUY.match(text)
    if b:
        return {'type': 'aa_spend', 'ts': ts, 'ability': b.group(1), 'points': int(b.group(2))}
    i = RE_AA_IMPROVE.match(text)
    if i:
        return {'type': 'aa_spend', 'ts': ts, 'ability': i.group(1), 'points': int(i.group(2))}
    return None


def _depot(text: str, ts: float) -> Optional[dict]:
    d = RE_DEPOT_DEPOSIT.match(text)
    if d:
        return {'type': 'depot_deposit', 'ts': ts, 'qty': int(d.group(1)), 'item': d.group(2)}
    w = RE_DEPOT_TAKE.match(text)
    if w:
        return {'type': 'depot_withdraw', 'ts': ts, 'qty': int(w.group(1)), 'item': w.group(2)}
    return None   # 'Consumed N x …' falls through to the vendored depot_consume


def _craft_error(text: str, ts: float) -> Optional[dict]:
    reason = CRAFT_ERRORS.get(text)
    return {'type': 'craft_error', 'ts': ts, 'reason': reason} if reason else None


def _merge(text: str, ts: float) -> Optional[dict]:
    m = RE_MERGE.match(text)
    if not m:
        return None
    item = m.group(1).strip()
    tm = RE_MERGE_TIER.search(item)
    return {'type': 'upgrade', 'ts': ts, 'item': item,
            'base': RE_MERGE_TIER.sub('', item) if tm else item,
            'tier': int(tm.group(1)) if tm else None}


def parse(line: str, pet_name: Optional[str] = None,
          group_members: Optional[Set[str]] = None) -> Optional[dict]:
    # cheap substring gates: a few hundred of ~1.4M live-log lines pass any of them
    handler = None
    if 'ability point' in line:
        handler = _aa
    elif 'personal depot' in line:
        handler = _depot
    elif 'merged two items' in line:
        handler = _merge
    elif 'combine' in line or line.endswith('general inventory.'):
        handler = _craft_error
    if handler:
        m = RE_TS.match(line)
        if m:
            ts = _ts(m.group(1))
            if ts is not None:
                ev = handler(m.group(2), ts)
                if ev:
                    return ev
    return parse_line(line, pet_name, group_members)
