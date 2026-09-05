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

Auto-sold and auto-merged loot (4,656 + 160 on the reference log — the largest
loot shape in the game, and the vendored parser has no regex for it):
  "You looted 2 Zombie Skin from a tormented dead's corpse and sold it for 1 gold, 3 silver and 6 copper."
  "You looted a Rusty Broad Sword +1 from a tormented dead's corpse and sold it for free."
  "You looted a Throwing Boulder from a hill giant's corpse to create a Throwing Boulder +2"
Emitted as ordinary `loot` events (item, source, qty) so every consumer — the
fight tracker's loot list, the zone clock, loot history — sees them, with
`sold_copper` / `merged_into` added for the counters.
"""
import re
from typing import Optional, Set

# RE_TS and _ts are the vendored timestamp matcher and its memo cache; sharing
# them means both parse paths hit one strptime cache instead of two.
# _parse_coin turns "1 gold, 3 silver and 6 copper" into copper (None if not coin).
from vendor.eqlparser.parser import _NO_FLAGS, RE_TS, _parse_coin, _ts, parse_line

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

# XP the vendored RE_XP misses: it anchors on "experience!", so the bonus form
# never matched. This is not a rounding error — the game switched to the bonus
# wording in a patch, and on the reference log the LAST regular XP line is
# 2026-09-03 23:38 while all 524 lines after it are the bonus form. Every XP
# figure in the app (xp_pct, zone_stats, Fight.xp, XP per hour) had been reading
# zero since that day.
RE_XP_BONUS = re.compile(
    r'^You gain (?:party )?experience \(with a bonus\)!(?: \(([\d.]+)%\))?$')

# DoT ticks landing on YOU: 4,126 lines worth 136,502 HP that never reached
# damage_taken, because the vendored parser has only the "<mob> has taken N
# damage from YOUR <spell>" form. The caster is optional — 10 of these read
# "You have taken 40 damage from Stinging Swarm." with no " by <caster>".
#
# Anchored on "You have taken" on purpose. The third-party form ("A crocodile
# has taken 1 damage from Disease Cloud by Kirgon", 29k lines) is deliberately
# NOT parsed: none of those name the player, and emitting them as damage would
# credit strangers' raid fights to your meters — the same trap the vendored
# parser documents for RE_OTHER_MELEE. Group DPS, if ever wanted, has to be
# gated on group_members the way that regex is.
RE_DOT_TAKEN = re.compile(
    r'^You have taken (\d+) damage from (.+?)(?: by (.+?))?\.$')

RE_LOOT_SOLD = re.compile(
    r"^You looted (?:(\d+) )?(?:a |an |the )?(.+?) from (.+?)'s corpse and sold it for (.+?)\.?$")
RE_LOOT_MERGED = re.compile(
    r"^You looted (?:(\d+) )?(?:a |an |the )?(.+?) from (.+?)'s corpse to create (?:a |an |the )?(.+?)\.?$")

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


def _loot_auto(text: str, ts: float) -> Optional[dict]:
    m = RE_LOOT_SOLD.match(text)
    if m:
        price = m.group(4).strip()
        copper = 0 if price.lower() == 'free' else _parse_coin(price)
        return {'type': 'loot', 'ts': ts, 'item': m.group(2), 'source': m.group(3),
                'qty': int(m.group(1) or 1), 'copper': None,
                'sold_copper': copper if copper is not None else 0}
    m = RE_LOOT_MERGED.match(text)
    if m:
        return {'type': 'loot', 'ts': ts, 'item': m.group(2), 'source': m.group(3),
                'qty': int(m.group(1) or 1), 'copper': None, 'merged_into': m.group(4)}
    return None   # "…and stored it in your tradeskill depot" falls through to the vendored regex


def _xp_bonus(text: str, ts: float) -> Optional[dict]:
    """The bonus form the vendored RE_XP cannot see. Emitted as an ordinary `xp`
    event so every existing consumer — the fight tracker, the zone clock, the
    session clock — picks it up with no branch of its own."""
    m = RE_XP_BONUS.match(text)
    if not m:
        return None
    try:
        pct = float(m.group(1))
    except (TypeError, ValueError):
        pct = 0.0
    return {'type': 'xp', 'ts': ts, 'pct': pct, 'bonus': True}


def _dot_taken(text: str, ts: float) -> Optional[dict]:
    """A DoT tick landing on you. Carries the vendored flag keys so the fight
    tracker can consume it like any other damage_taken."""
    m = RE_DOT_TAKEN.match(text)
    if not m:
        return None
    spell, caster = m.group(2), m.group(3)
    return {'type': 'damage_taken', 'ts': ts, 'victim': 'player',
            'source': caster or spell, 'amount': int(m.group(1)),
            'dmg_type': 'dot', 'spell': spell, 'verb': 'dot',
            **_NO_FLAGS}


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
    elif "'s corpse and sold it" in line or "'s corpse to create" in line:
        handler = _loot_auto
    elif 'combine' in line or line.endswith('general inventory.'):
        handler = _craft_error
    elif 'with a bonus)!' in line:
        handler = _xp_bonus
    elif ' damage from ' in line:      # 'personal depot' is matched above, so the
        handler = _dot_taken           # "You have taken N Kiola Nut" lines never land here
    if handler:
        m = RE_TS.match(line)
        if m:
            ts = _ts(m.group(1))
            if ts is not None:
                ev = handler(m.group(2), ts)
                if ev:
                    return ev
    return parse_line(line, pet_name, group_members)
