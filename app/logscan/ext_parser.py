"""App-specific log events layered over the vendored parser — M3 milestone.

Contract: parse(line, pet_name=None, group_members=None) -> Optional[dict].
Tries EQL-Assistant-specific regexes FIRST (aa_gain, aa_spend), then falls
through to vendored parse_line. Never edit vendor/eqlparser to add events.

Known target lines (verified in the real log):
  'You have gained an ability point!  You now have 3 ability points.'
  'You have gained the ability "Ambidexterity" at a cost of 9 ability points.'
"""
from typing import Optional, Set

from vendor.eqlparser.parser import parse_line


def parse(line: str, pet_name: Optional[str] = None,
          group_members: Optional[Set[str]] = None) -> Optional[dict]:
    return parse_line(line, pet_name, group_members)
