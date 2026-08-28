"""Historical log scan — M3 milestone. Stub until then.

Contract: start(character) launches ONE background scan thread for that
character's log (no-op if one is running). Progress goes to state.set_import();
results land in skill_levels/level_history/aa_ledger/deaths/highlights with the
log_source byte-offset checkpoint written in the same transaction as each flush.
"""


def start(character: dict) -> dict:
    return {'ok': False, 'error': 'log import arrives in milestone M3'}
