"""App-specific log events layered over the vendored parser — M3 milestone.

Contract: parse(line, pet_name=None, group_members=None) -> Optional[dict].
Tries EQL-Assistant-specific regexes FIRST (aa_gain, aa_spend), then falls
through to vendored parse_line. Never edit vendor/eqlparser to add events.

All three AA shapes verified against the live log (182 lines, all accounted):
  'You have gained an ability point!  You now have 12 ability points.'   x118
      (double space after '!', singular 'point.' when the balance is 1)
  'You have gained the ability "Ambidexterity" at a cost of 9 ability points.'  x32
      (always 'points', even for costs of 0 and 1)
  'You have improved Combat Fury 2 at a cost of 2 ability points.'       x32
      (rank upgrades; one singular 'point.' occurrence, so tolerate both)
The improved-rank name keeps its trailing rank number ("Combat Fury 2") on
purpose: each rank is a distinct purchase and aa_ledger's PK includes the
ability name, so folding ranks together would drop rows.
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


def parse(line: str, pet_name: Optional[str] = None,
          group_members: Optional[Set[str]] = None) -> Optional[dict]:
    # cheap substring gate: only 182 of ~1.4M live-log lines contain this
    if 'ability point' in line:
        m = RE_TS.match(line)
        if m:
            ts = _ts(m.group(1))
            if ts is not None:
                text = m.group(2)
                g = RE_AA_GAIN.match(text)
                if g:
                    return {'type': 'aa_gain', 'ts': ts, 'points': 1,
                            'balance_after': int(g.group(1))}
                b = RE_AA_BUY.match(text)
                if b:
                    return {'type': 'aa_spend', 'ts': ts, 'ability': b.group(1),
                            'points': int(b.group(2))}
                i = RE_AA_IMPROVE.match(text)
                if i:
                    return {'type': 'aa_spend', 'ts': ts, 'ability': i.group(1),
                            'points': int(i.group(2))}
    return parse_line(line, pet_name, group_members)
