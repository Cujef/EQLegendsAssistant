"""Display the character's real name where the parser says 'player'.

The vendored parser emits a fixed `'player'` actor key (parser.py), and the
fight tracker stores it that way. That key stays the INTERNAL identity — it is
what lands in the database, so history keeps its meaning if the character is
renamed or a different character is imported. Substitution happens on the way
OUT (live snapshot, fight detail endpoint), never on the way in.
"""
from typing import Optional

PLAYER = 'player'


def _rename_keys(d: Optional[dict], name: str) -> None:
    if isinstance(d, dict) and PLAYER in d:
        d[name] = d.pop(PLAYER)


def humanize_fight(fight: Optional[dict], name: Optional[str]) -> Optional[dict]:
    """Rewrite 'player' to `name` throughout one Fight.to_dict() blob, in place.

    Covers the three meters, each tanking source's by_victim breakdown, and the
    per-event hit log. Returns the same object for call-site convenience.
    """
    if not fight or not name or name == PLAYER:
        return fight
    for meter in ('damage', 'healing', 'tanking'):
        _rename_keys(fight.get(meter), name)
    for src in (fight.get('tanking') or {}).values():
        if isinstance(src, dict):
            _rename_keys(src.get('by_victim'), name)
    for hit in (fight.get('hits') or []):
        if isinstance(hit, dict):
            for field in ('actor', 'tgt'):
                if hit.get(field) == PLAYER:
                    hit[field] = name
    for off_key in ('actors', 'verbs'):
        _rename_keys((fight.get('offense') or {}).get(off_key), name)
    return fight


def humanize_live(payload: dict, name: Optional[str]) -> dict:
    """Same substitution across a whole live-snapshot payload, in place."""
    if not name or name == PLAYER:
        return payload
    humanize_fight(payload.get('active_fight'), name)
    for f in (payload.get('fights') or []):
        humanize_fight(f, name)
    payload['player_name'] = name
    return payload
