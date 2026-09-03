"""EQ Legends log line parser — returns structured event dicts."""
import re
from datetime import datetime
from typing import Optional, Set

RE_TS = re.compile(r'^\[(.+?)\] (.*)$')

# Optional trailing tag EQ appends to melee lines, e.g. "... damage. (Riposte Critical)".
# The tag is a space-separated token SET, not a fixed enum — the live log carries 15 distinct
# combinations. Capture it whole and decompose in _flags(); anything unrecognized degrades to
# "no flags set" instead of failing the match and silently discarding the damage event.
_SUFFIX = r'(?:\s*\(([^)]+)\))?'

_FLAG_TOKENS = (
    ('is_crit',          'critical'),
    ('is_riposte',       'riposte'),
    ('is_strikethrough', 'strikethrough'),
    ('is_finishing',     'finishing blow'),
    ('is_slay_undead',   'slay undead'),
    ('is_crippling',     'crippling blow'),
    ('is_double_bow',    'double bow shot'),
)


def _flags(tag: Optional[str]) -> dict:
    """Decompose a trailing combat tag into boolean flags."""
    t = (tag or '').lower()
    return {name: token in t for name, token in _FLAG_TOKENS}


_NO_FLAGS = _flags(None)

# Melee verbs, in the bare/1st-person form EQ uses for "You <verb>" and "tries to <verb>".
# Every entry here was observed in the live log.
_MELEE_VERBS = [
    'frenzy on', 'backstab', 'slash', 'pierce', 'crush', 'bash', 'kick', 'punch',
    'bite', 'claw', 'gore', 'maul', 'rend', 'slice', 'sting', 'strike', 'smite',
    'cleave', 'reave', 'smash', 'shoot', 'hit',
]


def _pluralize(verb: str) -> str:
    if verb == 'frenzy on':
        return 'frenzies on'
    if verb.endswith(('s', 'sh', 'ch', 'x', 'z')):
        return verb + 'es'
    return verb + 's'


# normalize every form (3rd-person plural, "frenzy on") to the canonical 1st-person verb
VERB_NORMALIZE = {}
for _v in _MELEE_VERBS:
    _base = 'frenzy' if _v == 'frenzy on' else _v
    VERB_NORMALIZE[_v] = _base
    VERB_NORMALIZE[_pluralize(_v)] = _base

# Longest-first so multi-word and plural forms win over their prefixes
# ("frenzies on" before "frenzy", "slashes" before "slash").
_VERB_ALT = '|'.join(re.escape(v) for v in sorted(VERB_NORMALIZE, key=len, reverse=True))
_VERB_BARE_ALT = '|'.join(re.escape(v) for v in sorted(_MELEE_VERBS, key=len, reverse=True))


def _norm_verb(v: str) -> str:
    return VERB_NORMALIZE.get(v, v)


# player damage to mobs
RE_YOU_MELEE = re.compile(
    r'^You (' + _VERB_BARE_ALT + r') (.+?) for (\d+) points? of damage\.' + _SUFFIX + r'$'
)
RE_YOU_SPELL = re.compile(r'^You hit (.+?) for (\d+) points? of \w+ damage by (.+?)\.$')
RE_YOU_DOT   = re.compile(r'^(.+?) has taken (\d+) damage from your (.+?)\.$')

# pet detection + pet damage
# "I am unable to wake <mob>, Master." is the enchanter-pet mez-assist refusal; it was the
# only pet tell missing from this alternation and cost 23 pet detections on the live log.
RE_PET_TELL  = re.compile(
    r'^(\w+) told you, \'(?:Attacking|Back|Following|Guarding|Changing|Sorry|No longer'
    r'|My leader|I am unable to wake)'
)
RE_PET_MELEE = re.compile(
    r'^(\w+) (' + _VERB_ALT + r') (.+?) for (\d+) points? of damage\.' + _SUFFIX + r'$'
)
RE_PET_SPELL = re.compile(r'^(\w+) hit (.+?) for (\d+) points? of \w+ damage by (.+?)\.$')

# other group members' damage (only trusted when the attacker is a known group member —
# otherwise this shape also matches unrelated nearby players/mobs fighting other things)
RE_OTHER_MELEE = re.compile(
    r'^(\w+) (' + _VERB_ALT + r') (.+?) for (\d+) points? of damage\.' + _SUFFIX + r'$'
)
RE_OTHER_SPELL = re.compile(r'^(\w+) hit (.+?) for (\d+) points? of \w+ damage by (.+?)\.$')

# group membership tracking
RE_GROUP_INVITE      = re.compile(r'^(\w+) invites you to join a group\.$')
RE_GROUP_JOINED      = re.compile(r'^You have joined the group\.$')
# The line you get as group LEADER when someone accepts. Cannot collide with
# RE_GROUP_JOINED — "has" vs "have" — and it is emitted as the existing `group_member_seen`
# so the server needs no new branch. 37 occurrences on the live log.
# Measured yield is modest and worth writing down so nobody re-measures it: A/B-ing this
# regex on and off over the whole log recovers 1,817 damage dealt and 1,209 taken, because
# every name that joins there also speaks in group chat within seconds and the group-tell
# regex was already claiming them. What this closes is the window between joining and first
# speaking — the only window a leader-side roster CAN close from the log. Members who were
# already grouped when logging started announce themselves with no line at all and stay
# unrecoverable; that is where the rest of the missing ally damage lives.
RE_GROUP_MEMBER_JOINED = re.compile(r'^(\w+) has joined the group\.$')
# Deliberately NOT parsed: "You invite <name> to join your group."
# An invite is not an acceptance — the invitee can decline, and whitelisting a stranger's
# name off an invite would let their damage into the group meters forever. The acceptance
# path already exists and is the one that counts: RE_GROUP_INVITE parks the name in
# server.pending_group_invite, and the join line (this regex, or RE_GROUP_JOINED) promotes
# it. Do not "complete" the set by adding the invite form.
RE_GROUP_MEMBER_LEFT = re.compile(r'^(\w+) has left the group\.$')
RE_GROUP_SELF_OUT    = re.compile(r'^You have (?:left|been removed from) the group\.$')
RE_GROUP_TELL        = re.compile(r'^(\w+) tells the group, ')

# damage taken
RE_MELEE_YOU = re.compile(
    r'^(.+?) (' + _VERB_ALT + r') YOU for (\d+) points? of damage\.' + _SUFFIX + r'$'
)
RE_SPELL_YOU = re.compile(
    r'^(.+?) hit you for (\d+) points? of \w+ damage by (.+?)\.$', re.IGNORECASE
)
# damage taken by the pet OR by a group member — same shape as damage to YOU but with an
# ally's name as the target. Deliberately broad; the caller only trusts it when group(3) is
# the known pet or a current group member. THE GATE IS LOAD-BEARING: 317 names that are not
# in any group match this exact shape on the live log, carrying 1,765,789 damage from other
# people's fights. Melee only — there is deliberately no ally-spell-taken regex, because the
# 1,147,683 measured figure is a melee measurement and a speculative spell form is exactly
# the over-matching this parser has been bitten by before.
RE_MELEE_PET = re.compile(
    r'^(.+?) (' + _VERB_ALT + r') (\w+) for (\d+) points? of damage\.' + _SUFFIX + r'$'
)

# ── misses / avoidance ──────────────────────────────────────────────────────────
# "You try to slash a Tesch Mas Gnoll, but miss!"
# "You try to pierce a tormented dead, but a tormented dead dodges!"
# "You try to bash X, but X's magical skin absorbs the blow!"
RE_YOU_MISS = re.compile(
    r'^You try to (' + _VERB_BARE_ALT + r') (.+?), but (?:'
    r'miss(?:es)?'
    r"|(?P<absorber>.+?)'s magical skin absorbs the blow"
    r'|(?P<avoider>.+?) (?P<avoid>dodges|parries|ripostes|blocks)'
    r')!' + _SUFFIX + r'$'
)
# "A dread skeleton tries to kick YOU, but YOU riposte!"
RE_MISS_YOU = re.compile(
    r'^(.+?) tries to (' + _VERB_BARE_ALT + r') YOU, but (?:'
    r'misses'
    r'|YOUR magical skin absorbs the blow'
    r'|YOU (?P<avoid>dodge|parry|riposte|block)'
    r')!' + _SUFFIX + r'$'
)
# pet swinging and missing — same shape, attacker name gated on pet_name by the caller
RE_PET_MISS = re.compile(
    r'^(\w+) tries to (' + _VERB_ALT + r') (.+?), but (?:'
    r'misses'
    r"|(?P<absorber>.+?)'s magical skin absorbs the blow"
    r'|(?P<avoider>.+?) (?P<avoid>dodges|parries|ripostes|blocks)'
    r')!' + _SUFFIX + r'$'
)

_AVOID_NORMALIZE = {
    'dodges': 'dodge', 'parries': 'parry', 'ripostes': 'riposte', 'blocks': 'block',
    'dodge': 'dodge', 'parry': 'parry', 'riposte': 'riposte', 'block': 'block',
}

# ── damage shields / procs ("non-melee" damage) ─────────────────────────────────
# "A tormented dead is pierced by YOUR thorns for 7 points of non-melee damage."
RE_DS_OUT = re.compile(
    r'^(.+?) is \w+ by YOUR (.+?) for (\d+) points? of non-melee damage[.!]$'
)
# "YOU are burned by a Tesch Mas Gnoll's flames for 12 points of non-melee damage!"
RE_DS_IN = re.compile(
    r"^YOU are \w+ by (.+?)'s (.+?) for (\d+) points? of non-melee damage[.!]$"
)
# "A greater kobold is pierced by Burro's thorns for 3 points of non-melee damage."
RE_DS_OTHER = re.compile(
    r"^(.+?) is \w+ by (\w+)'s (.+?) for (\d+) points? of non-melee damage[.!]$"
)

# A group member swinging and missing. Identical in shape to RE_PET_MISS — the only thing
# that tells a member's swing from the pet's is which set the caller checks the name
# against, so the two share one compiled pattern rather than duplicating it.
#
# This is the regex the README used to say could not exist. It claimed "your log records
# their hits but not their misses, so any accuracy number would be a fabricated 100%".
# That was wrong: the misses are right there, 40,430 of them while grouped on the
# reference log, and discarding them is what made accuracy look uncomputable.
RE_OTHER_MISS = RE_PET_MISS

# ── faction ───────────────────────────────────────────────────────────────────
# "Your faction standing with Frogloks of Guk has been adjusted by -5."
RE_FACTION_ADJ = re.compile(
    r'^Your faction standing with (.+?) has been adjusted by (-?\d+)\.$'
)
# "Your faction standing with Faydarks Champions could not possibly get any better."
# Emitted as its own event rather than a 0 adjustment: "already maxed" and "no change"
# are different facts, and folding them together would make a capped faction look idle.
RE_FACTION_CAP = re.compile(
    r'^Your faction standing with (.+?) could not possibly get any (better|worse)\.$'
)

# ── tradeskills ───────────────────────────────────────────────────────────────
# "You have fashioned the items together to create something new: Tumpy Tonic."
RE_TS_MADE = re.compile(
    r'^You have fashioned the items together to create something new: (.+?)\.$'
)
# "You lacked the skills to fashion Tumpy Tonic." — the failure names the item too, so
# success rate is per recipe rather than a single global number.
RE_TS_FAILED = re.compile(r'^You lacked the skills to fashion (.+?)\.$')
# Skill is capped for this recipe: the combine still works, it just no longer trains.
RE_TS_CAPPED = re.compile(
    r'^You can no longer advance your skill from making this item\.$'
)
# "Consumed 2 x Water Flask (leaving 7) from your personal depot."
RE_DEPOT_CONSUME = re.compile(
    r'^Consumed (\d+) x (.+?) \(leaving (\d+)\) from your personal depot\.?$'
)

# healing (over-time pattern is more specific — check first)
RE_HEAL_OT = re.compile(
    r'^(.+?) healed (.+?) over time for (\d+)(?:\s*\((\d+)\))? hit points?(?: by (.+?))?\.$'
)
RE_HEAL = re.compile(
    r'^(.+?) healed (.+?) for (\d+)(?:\s*\((\d+)\))? hit points?(?: by (.+?))?\.$'
)

# spells
RE_CAST      = re.compile(r'^You begin casting (.+?)\.$')
RE_FIZZLE    = re.compile(r'^Your (.+?) spell fizzles!$')
RE_OTHER_CAST = re.compile(r'^(.+?) begins casting (.+?)\.$')

# kills / deaths
RE_YOU_KILL = re.compile(r'^You have slain (.+?)!$')
RE_YOU_DIED = re.compile(r'^You have been slain by (.+?)!?$')

# resists — live log format is "A willowisp resisted your Ignite!" (no " spell" suffix);
# the optional group keeps compatibility with the older "... your X spell." phrasing
RE_RESIST_MOB  = re.compile(r'^(.+?) resist(?:s|ed) your (.+?)(?: spell)?[!.]$')
RE_RESIST_SELF = re.compile(r'^Your target resisted your (.+?)(?: spell)?[!.]$')
RE_RESIST_YOU  = re.compile(r"^You resist (.+?)'s (.+?)!$")

# ── buffs ───────────────────────────────────────────────────────────────────────
# Your OWN buffs never use "spell has worn off" — that form only ever covers debuffs on a
# mob ("worn off of <target>") and pet buffs. Self buffs announce themselves with per-spell
# flavor emotes, so buff state has to come from an emote table. Haste — the case this was
# built for — lands as "You feel your pulse quicken." and drops as "Your speed returns to
# normal.", which is why a generic "worn off" regex would never fire for Celerity.
BUFF_EMOTES = {
    # haste line (Celerity / Quickness / Alacrity / Augmentation)
    'You feel your pulse quicken.':                             ('Haste', 'up'),
    'Your speed returns to normal.':                            ('Haste', 'down'),
    # movement speed (Spirit of Wolf line)
    'You feel the spirit of wolf enter you.':                   ('Movement Speed', 'up'),
    'You feel much faster.':                                    ('Movement Speed', 'up'),
    'Your feet slow down.':                                     ('Movement Speed', 'down'),
    # mana / clarity
    'You feel your mind clear.':                                ('Clarity', 'up'),
    'Your clarity of mind fades.':                              ('Clarity', 'down'),
    # melee buffs
    'You feel a rush of battle fury.':                          ('Battle Fury', 'up'),
    'Your battle fury fades.':                                  ('Battle Fury', 'down'),
    # stats
    'You feel stronger.':                                       ('Strength', 'up'),
    'You feel strong.':                                         ('Strength', 'up'),
    'You feel the spirit of ox enter you.':                     ('Strength', 'up'),
    'Your strength fades.':                                     ('Strength', 'down'),
    'You feel dexterous.':                                      ('Dexterity', 'up'),
    'You feel the spirit of monkey enter you.':                 ('Dexterity', 'up'),
    'Your dexterity fades.':                                    ('Dexterity', 'down'),
    'You feel nimble.':                                         ('Agility', 'up'),
    'You feel agile.':                                          ('Agility', 'up'),
    'You feel more agile.':                                     ('Agility', 'up'),
    'You feel the spirit of cat enter you.':                    ('Agility', 'up'),
    'Your agility fades.':                                      ('Agility', 'down'),
    'You feel robust.':                                         ('Stamina', 'up'),
    'You feel tough.':                                          ('Stamina', 'up'),
    'You feel the spirit of bear enter you.':                   ('Stamina', 'up'),
    # hit points
    'You feel healthy.':                                        ('Health', 'up'),
    'Your health fades.':                                       ('Health', 'down'),
    'Your hit points fade.':                                    ('Hit Points', 'down'),
    # armor / protection
    'You feel armored.':                                        ('Armor Class', 'up'),
    'You feel an aura of protection engulf you.':               ('Protection', 'up'),
    'You feel an aura of vigorous protection surrounding you.': ('Protection', 'up'),
    'You feel an aura of mystic protection surrounding you.':   ('Protection', 'up'),
    'Your protection fades.':                                   ('Protection', 'down'),
    'Your shielding fades.':                                    ('Shielding', 'down'),
    'Your spiritual armor fades.':                              ('Spiritual Armor', 'down'),
    'Your sense of center fades.':                              ('Center', 'down'),
    # damage shields
    'You feel your skin ignite.':                               ('Damage Shield', 'up'),
    'You feel your skin freeze.':                               ('Damage Shield', 'up'),
    'You feel your skin smolder.':                              ('Damage Shield', 'up'),
    'Your skin returns to normal.':                             ('Damage Shield', 'down'),
    # resists
    'You feel resistant to fire.':                              ('Fire Resist', 'up'),
    'You feel protected from fire.':                            ('Fire Resist', 'up'),
    'Your endurance to fire fades.':                            ('Fire Resist', 'down'),
    'You feel resistant to magic.':                             ('Magic Resist', 'up'),
    'You feel protected from magic.':                           ('Magic Resist', 'up'),
    'Your endurance to magic fades.':                           ('Magic Resist', 'down'),
    # misc
    'You feel the favor of the gods upon you.':                 ('Divine Favor', 'up'),
    'Your divine favor fades.':                                 ('Divine Favor', 'down'),
    'Your illusion fades.':                                     ('Illusion', 'down'),
    'Your infravision fades.':                                  ('Infravision', 'down'),
    # 'Your vulnerability fades.' moved to PLAYER_STATE_EMOTES — it ends a debuff, not a buff
    'The echo of healing fades away.':                          ('Echo of Healing', 'down'),
    'The mystical path fades away.':                            ('Mystical Path', 'down'),
    'You feel the tortoise spirit depart.':                     ('Tortoise', 'down'),
}

# ── player detriment states ─────────────────────────────────────────────────────
# EQ Legends never prints "You are mesmerized / charmed / feared / rooted". Every
# crowd-control and debuff effect arrives as a per-spell flavor emote, so detriment state
# has to come from an exact-match table for the same reason BUFF_EMOTES exists. Checked
# BEFORE BUFF_EMOTES: a couple of lines ("Your vulnerability fades.") read like a buff
# fading but actually end a detriment.
#
# TRAPS — positives that read as negatives. Every one of these is deliberately ABSENT
# from this table and pinned by a selftest case, because misfiling any of them would put
# a permanent false "danger" banner on the HUD:
#   'Your mind begins to clear.'  (1844)  bard Clarity mana tick — NOT mez ending
#   'Your mind clears.'           (657)   same family
#   'You slow down.'              (146)   Selo's Accelerando re-fire pulse — NOT a snare
#   'Your feet slow down.'        (54)    Movement Speed buff dropping (BUFF_EMOTES owns it)
#   'Your feet leave the ground.' (10)    levitate landing
#
# Loss of control is one shared start line for mez/charm/fear; the cause is only revealed
# by whichever "no longer …" line ends it, so the off events carry `cause` and the client
# retro-labels the episode.
#
# value = (state, 'on'|'off', severity, cause)
PLAYER_STATE_EMOTES = {
    # ── control-severity: you cannot act ──
    'You lose control of yourself!':        ('Controlled', 'on',  'control', None),
    'You are no longer captivated.':        ('Controlled', 'off', 'control', 'Mesmerized'),
    'You are no longer afraid.':            ('Controlled', 'off', 'control', 'Feared'),
    'You are no longer charmed.':           ('Controlled', 'off', 'control', 'Charmed'),
    'You are no longer entranced.':         ('Controlled', 'off', 'control', 'Entranced'),
    'You have control of yourself again.':  ('Controlled', 'off', 'control', None),
    # Screaming Terror is the one fear with its own pair
    'You begin to scream.':                 ('Feared', 'on',  'control', 'Screaming Terror'),
    'You stop screaming.':                  ('Feared', 'off', 'control', 'Screaming Terror'),
    'You have been knocked unconscious!':   ('Unconscious', 'on',  'control', None),
    'You are conscious again!':             ('Unconscious', 'off', 'control', None),

    # ── minor-severity: you can still act ──
    # root: four different spells, one state
    'Your feet adhere to the ground.':              ('Rooted', 'on',  'minor', None),
    'Your feet sink into the ground.':              ('Rooted', 'on',  'minor', None),
    'Your feet become entwined.':                   ('Rooted', 'on',  'minor', None),
    'Bonds of force bind your feet to the ground.': ('Rooted', 'on',  'minor', None),
    'Your feet come free.':                         ('Rooted', 'off', 'minor', None),
    'The roots fall from your feet.':               ('Rooted', 'off', 'minor', None),
    # snare / cripple
    'Your legs feel weak.':          ('Snared', 'on',  'minor', None),
    'Strength returns to your legs.':('Snared', 'off', 'minor', None),
    'You are ensnared.':             ('Snared', 'on',  'minor', None),
    'You are no longer ensnared.':   ('Snared', 'off', 'minor', None),
    # tangling weeds is a slow, not a root — kept apart so neither count is polluted
    'You slow down as your feet are covered in tangling weeds.':
                                     ('Entangled', 'on',  'minor', 'Tangling Weeds'),
    'The tangling weeds wither away.':('Entangled', 'off', 'minor', 'Tangling Weeds'),
    # damage-over-time and stat debuffs
    'You have been diseased.':       ('Diseased', 'on',  'minor', None),
    'You are no longer diseased.':   ('Diseased', 'off', 'minor', None),
    'You have been poisoned.':       ('Poisoned', 'on',  'minor', None),
    'You are no longer poisoned.':   ('Poisoned', 'off', 'minor', None),
    'Your blood boils.':             ('Boiling Blood', 'on',  'minor', None),
    'Your blood cools.':             ('Boiling Blood', 'off', 'minor', None),
    'You feel a shortness of breath.':('Suffocating', 'on',  'minor', None),
    'You can breathe again.':        ('Suffocating', 'off', 'minor', None),
    'You are encumbered!':           ('Encumbered', 'on',  'minor', None),
    'You are no longer encumbered.': ('Encumbered', 'off', 'minor', None),
    'You feel dazed.':               ('Dazed', 'on',  'minor', None),
    'You no longer feel dazed.':     ('Dazed', 'off', 'minor', None),
    'You feel drowsy.':              ('Drowsy', 'on',  'minor', None),
    'You feel less drowsy.':         ('Drowsy', 'off', 'minor', None),
    'You feel sleepy.':              ('Sleepy', 'on',  'minor', None),
    'You feel less sleepy.':         ('Sleepy', 'off', 'minor', None),
    'You feel somewhat vulnerable.': ('Vulnerable', 'on',  'minor', None),
    'You feel very vulnerable.':     ('Vulnerable', 'on',  'minor', None),
    'You feel vulnerable.':          ('Vulnerable', 'on',  'minor', None),
    'Your vulnerability fades.':     ('Vulnerable', 'off', 'minor', None),
    'You feel feverish.':            ('Fevered', 'on',  'minor', None),
    'Your fever has broken.':        ('Fevered', 'off', 'minor', None),
    'Your stomach begins to cramp.': ('Cramping', 'on',  'minor', None),
    'Your stomach feels better.':    ('Cramping', 'off', 'minor', None),
    'You feel lethargic.':           ('Lethargic', 'on',  'minor', None),
    'You are no longer lethargic.':  ('Lethargic', 'off', 'minor', None),
}

# Start-only detriments. The log carries no matching end line for any of these, so they
# are reported as a one-shot flash (banner pulse + history entry) instead of a state that
# would otherwise sit "active" on the HUD forever. value = (label, severity).
PLAYER_STATE_FLASH = {
    'Your mind fills with fear.':                     ('Fear', 'control'),
    'You are stunned by a gust of air.':              ('Stunned', 'control'),
    'You have been summoned!':                        ('Summoned', 'minor'),
    'You are bleeding to death!':                     ('Bleeding', 'minor'),
    # environmental / ambient hits
    'Your body spasms as the lightning bolt arcs through you.': ('Lightning', 'minor'),
    'You have been struck down by wrath.':            ('Wrath', 'minor'),
    'You have been lacerated.':                       ('Laceration', 'minor'),
    'You have been struck by the force of Ykesha.':   ('Ykesha', 'minor'),
    'You are struck by a sudden force.':              ('Force', 'minor'),
    'You are struck by a sudden burst of force.':     ('Force', 'minor'),
    'You are wracked with pain.':                     ('Pain', 'minor'),
    'You are wracked by pain.':                       ('Pain', 'minor'),
    'You are engulfed by darkness.':                  ('Darkness', 'minor'),
    'You are in the grip of darkness.':               ('Darkness', 'minor'),
    'You are shrouded by anti-life magic.':           ('Anti-life', 'minor'),
    'You are slashed by shards of ice.':              ('Ice', 'minor'),
    'You are entombed in elemental ice.':             ('Ice', 'minor'),
    'You are chilled by a bolt of frost.':            ('Frost', 'minor'),
    'You are encased in frost.':                      ('Frost', 'minor'),
    'You are trapped within a whirling wind.':        ('Wind', 'minor'),
    'You are blasted by blazing winds.':              ('Wind', 'minor'),
    'You are engulfed by lightning.':                 ('Lightning', 'minor'),
    'You are caught in a torrent of fire.':           ('Fire', 'minor'),
    'You are enveloped in blazing energy.':           ('Fire', 'minor'),
    'You are surrounded by flickering flames.':       ('Fire', 'minor'),
    'Your body is encased in fire.':                  ('Fire', 'minor'),
    'Your brain begins to smolder.':                  ('Mind Burn', 'minor'),
    'Your world goes mad as chaos flows through you.':('Chaos', 'minor'),
}

# ── mob-side crowd control ──────────────────────────────────────────────────────
# None of these has an "it wore off" line; only mez has an end event, and it is the one
# that matters — "has been awakened by" is a MEZ BREAK, i.e. an add is now loose.
RE_MOB_MEZ      = re.compile(r'^(.+) has been mesmerized\.$')
RE_MOB_ENTHRALL = re.compile(r'^(.+) has been enthralled\.$')
RE_MOB_CHARM    = re.compile(r'^(.+) has been charmed\.$')
RE_MOB_ENSNARE  = re.compile(r'^(.+) has been ensnared\.$')
RE_MOB_STUN     = re.compile(r'^(.+) is stunned by (.+)\.$')
RE_MOB_WAKE     = re.compile(r'^(.+) has been awakened by (.+)\.$')
# Generic death line. EQ has no "your pet has been slain" — a pet death is only visible
# here, which is why pet safety depends on a resolved pet name. Must be tested AFTER
# RE_YOU_DIED, whose text is a special case of this shape.
RE_SLAIN_BY     = re.compile(r'^(.+) has been slain by (.+)!$')

# ── casting failures ────────────────────────────────────────────────────────────
RE_CAST_INTERRUPT = re.compile(r'^Your (.+?) spell is interrupted\.$')
RE_CAST_BLOCKED   = re.compile(
    r'^Your (.+?) spell did not take hold(?: on (.+?))?\. \(Blocked by (.+?)\.\)$'
)
# Every fixed-text failure the live log actually produces, with its measured frequency.
CAST_FAIL_LINES = {
    'Your target is too far away, get closer!':      'range',        # 2280
    'Your target is out of range, get closer!':      'range',        #   34
    'You cannot see your target.':                   'no_los',       # 2218
    "You can't cast spells while stunned!":          'stunned',      # 1313
    'You are missing some required components.':     'components',   #    6
    'You must be standing to cast a spell.':         'standing',     #    3
    'You are too distracted to cast a spell now!':   'distracted',   #    2
    'Insufficient Mana to cast this spell!':         'mana',         #   24 (only form)
    'You are already casting a spell!':              'busy',         #    1
}
RE_CAST_SAVE = re.compile(r'^You regain your concentration and continue your casting\.$')

# progression
RE_LEVEL_UP = re.compile(r'^You have gained a level! Welcome to level (\d+)!$')

# pet buff fade — this generic form DOES work, but only for the pet
RE_PET_BUFF_FADE = re.compile(r"^Your pet's (.+?) spell has worn off\.$")
# self buff fade, generic form — rare but harmless to support alongside the emote table
RE_SELF_BUFF_FADE = re.compile(r'^Your (.+?) spell has worn off\.$')
# debuff/DoT wearing off a mob — gives us an end timestamp to pair with the cast/first tick
RE_DEBUFF_WORNOFF = re.compile(r'^Your (.+?) spell has worn off of (.+?)\.$')

# Shape of a buff-ish or state-ish emote we do not yet recognize. Surfacing these lets the
# tables be extended from real misses instead of guesswork. Widened in v1.2.0 to the three
# shapes detriments actually use ("You have been …", "You are no longer …", "… returns to
# your legs.") so a future unknown state lands in `unknown_emotes` instead of vanishing.
# The `[^:]` guard keeps the "You have been granted the following spell: X." family out.
RE_EMOTE_CANDIDATE = re.compile(
    r'^(?:You feel .+'
    r'|You have been [^:]{0,30}\.'
    r'|You are no longer [^:]{0,30}\.'
    r'|.{0,45} returns to your legs\.'
    r'|Your .{0,45}(?:fades?|returns to normal|slow down)\.)$'
)

# loot
# A merchant sale uses the same "You receive <coin> from <name>" shape as a corpse
# payout but ends with "for the <item>(s)." — it is neither loot nor kill income, and
# counting it would double-count an item you already looted and then sold.
RE_VENDOR_SALE = re.compile(r'^You receive (.+?) from (.+?) for (?:the )?(.+?)\.$')
RE_LOOT_DASH  = re.compile(r'^--You have looted (?:a |an |the )?(.+?)\.--$')
RE_LOOT_PLAIN = re.compile(r'^You (?:have looted|received?) (.+?)\.?$')
# Auto-store loot uses a completely different verb ("You looted", no "have") and often has
# no trailing period, so none of the forms above ever matched it — 770 real drops on the
# live log. The leading count is captured because stacked components arrive as "2 Spider Silk".
RE_LOOT_DEPOT = re.compile(
    r"^You looted (?:(\d+) )?(?:a |an |the )?(.+?) from (.+?)'s corpse"
    r' and stored it in your tradeskill depot\.?$'
)
# splits "<item> from <source>['s corpse]" — greedy on the item so the split lands on the
# LAST " from ", keeping item names like "Cloak from the Deep" intact
RE_LOOT_FROM  = re.compile(r"^(.+) from (?:the corpse of )?(.+?)(?:'s corpse)?$")

# coin loot — "5 platinum, 2 gold, 3 silver and 4 copper" etc.
_COIN_VALUE   = {'platinum': 1000, 'gold': 100, 'silver': 10, 'copper': 1}
RE_COIN_TOKEN = re.compile(r'(\d+)\s*(platinum|gold|silver|copper)', re.IGNORECASE)


def _parse_coin(item: str) -> Optional[int]:
    """Return total copper value if `item` is purely a coin-loot description, else None."""
    tokens = RE_COIN_TOKEN.findall(item)
    if not tokens:
        return None
    residual = RE_COIN_TOKEN.sub('', item)
    residual = re.sub(r'\band\b', '', residual, flags=re.IGNORECASE).strip(' ,.')
    if residual:
        return None
    return sum(int(n) * _COIN_VALUE[denom.lower()] for n, denom in tokens)


def _split_loot(item: str) -> tuple:
    """Split a looted-item string into (item, source)."""
    m = RE_LOOT_FROM.match(item)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return item, 'Unknown'


# misc
RE_SESSION = re.compile(r"^(?:Logging to 'eqlog\.txt' is now \*ON\*\.|Welcome to EverQuest Legends!)$")
RE_ZONE    = re.compile(r'^You have entered (.+?)\.$')
RE_AUTOATTACK = re.compile(r'^Auto attack is (on|off)\.$')
RE_STUN_ON       = re.compile(r'^You are stunned!$')
RE_STUN_OFF      = re.compile(r'^You are no longer stunned\.$')
RE_STUN_OVERCOME = re.compile(r'^You overcome the stun!$')
RE_XP      = re.compile(r'^You gain (?:party )?experience!(?: \((.+?)\))?$')
RE_SKILL   = re.compile(r'^You have become better at (.+?)! \((\d+)\)$')


# strptime is the single most expensive call in the whole parse path (a third of it), and
# a busy log writes dozens of lines per second — so the same timestamp string repeats over
# and over. A small memo turns almost all of those into a dict hit, which is most of what
# makes a 7-day backfill finish in a reasonable time.
_TS_CACHE: dict = {}
_TS_CACHE_MAX = 4096


def _ts(s: str) -> Optional[float]:
    hit = _TS_CACHE.get(s, 0)
    if hit != 0:
        return hit if hit > 0 else None
    try:
        val = datetime.strptime(s, '%a %b %d %H:%M:%S %Y').timestamp()
    except ValueError:
        val = None
    if len(_TS_CACHE) >= _TS_CACHE_MAX:
        _TS_CACHE.clear()
    # -1 is the "known bad" sentinel; a real EQ timestamp is never <= 0
    _TS_CACHE[s] = val if val is not None else -1.0
    return val


def parse_line(line: str, pet_name: Optional[str] = None,
               group_members: Optional[Set[str]] = None) -> Optional[dict]:
    m = RE_TS.match(line)
    if not m:
        return None
    ts = _ts(m.group(1))
    if ts is None:
        return None
    text = m.group(2)

    # session / zone / misc
    if RE_SESSION.match(text):
        return {'type': 'session_start', 'ts': ts}
    zm = RE_ZONE.match(text)
    if zm:
        return {'type': 'zone', 'ts': ts, 'zone': zm.group(1)}
    xm = RE_XP.match(text)
    if xm:
        try:
            pct = float((xm.group(1) or '0').rstrip('%'))
        except ValueError:
            pct = 0.0
        return {'type': 'xp', 'ts': ts, 'pct': pct}
    skm = RE_SKILL.match(text)
    if skm:
        return {'type': 'skill', 'ts': ts, 'skill': skm.group(1), 'level': int(skm.group(2))}
    lvm = RE_LEVEL_UP.match(text)
    if lvm:
        return {'type': 'level_up', 'ts': ts, 'level': int(lvm.group(1))}
    aam = RE_AUTOATTACK.match(text)
    if aam:
        return {'type': 'autoattack', 'ts': ts, 'on': aam.group(1) == 'on'}
    if RE_STUN_ON.match(text):
        return {'type': 'stun', 'ts': ts, 'on': True}
    if RE_STUN_OVERCOME.match(text):
        return {'type': 'stun', 'ts': ts, 'on': False, 'overcome': True}
    if RE_STUN_OFF.match(text):
        return {'type': 'stun', 'ts': ts, 'on': False}

    # ── player detriment states (checked before buffs; both are exact-match) ──
    st = PLAYER_STATE_EMOTES.get(text)
    if st:
        ev = {'type': 'player_state', 'ts': ts, 'name': st[0], 'state': st[1],
              'severity': st[2]}
        if st[3]:
            ev['cause'] = st[3]
        return ev
    fl = PLAYER_STATE_FLASH.get(text)
    if fl:
        return {'type': 'player_state_flash', 'ts': ts, 'name': fl[0], 'severity': fl[1]}

    # ── buffs (exact-match emote table first; cheap and unambiguous) ──
    emote = BUFF_EMOTES.get(text)
    if emote:
        return {'type': 'buff', 'ts': ts, 'name': emote[0], 'state': emote[1], 'who': 'player'}
    pbf = RE_PET_BUFF_FADE.match(text)
    if pbf:
        return {'type': 'buff', 'ts': ts, 'name': pbf.group(1), 'state': 'down', 'who': 'pet'}
    # must be tested BEFORE the self form, which is a prefix of it
    dwm = RE_DEBUFF_WORNOFF.match(text)
    if dwm:
        return {'type': 'debuff_end', 'ts': ts, 'spell': dwm.group(1), 'target': dwm.group(2)}
    sbf = RE_SELF_BUFF_FADE.match(text)
    if sbf:
        return {'type': 'buff', 'ts': ts, 'name': sbf.group(1), 'state': 'down', 'who': 'player'}

    # pet name
    pm = RE_PET_TELL.match(text)
    if pm:
        return {'type': 'pet_name', 'ts': ts, 'name': pm.group(1)}

    # group membership
    gim = RE_GROUP_INVITE.match(text)
    if gim:
        return {'type': 'group_invite', 'ts': ts, 'name': gim.group(1)}
    if RE_GROUP_JOINED.match(text):
        return {'type': 'group_joined', 'ts': ts}
    gjm = RE_GROUP_MEMBER_JOINED.match(text)
    if gjm:
        # reuses `group_member_seen` on purpose: same meaning ("this name is one of ours"),
        # zero server diff, and replay.py's existing tally covers it for free
        return {'type': 'group_member_seen', 'ts': ts, 'name': gjm.group(1)}
    glm = RE_GROUP_MEMBER_LEFT.match(text)
    if glm:
        return {'type': 'group_member_left', 'ts': ts, 'name': glm.group(1)}
    if RE_GROUP_SELF_OUT.match(text):
        return {'type': 'group_disbanded', 'ts': ts}
    gtm = RE_GROUP_TELL.match(text)
    if gtm:
        return {'type': 'group_member_seen', 'ts': ts, 'name': gtm.group(1)}

    # spells
    cm = RE_CAST.match(text)
    if cm:
        return {'type': 'cast', 'ts': ts, 'spell': cm.group(1), 'caster': 'player', 'side': 'ally'}
    fm = RE_FIZZLE.match(text)
    if fm:
        return {'type': 'fizzle', 'ts': ts, 'spell': fm.group(1), 'caster': 'player', 'side': 'ally'}
    ocm = RE_OTHER_CAST.match(text)
    if ocm:
        name = ocm.group(1)
        is_ally = name == pet_name or bool(group_members and name in group_members)
        caster = 'pet' if name == pet_name else name
        return {'type': 'cast', 'ts': ts, 'spell': ocm.group(2), 'caster': caster,
                'side': 'ally' if is_ally else 'enemy'}

    # ── casting failures ──
    reason = CAST_FAIL_LINES.get(text)
    if reason:
        return {'type': 'cast_fail', 'ts': ts, 'reason': reason, 'spell': None}
    cim = RE_CAST_INTERRUPT.match(text)
    if cim:
        return {'type': 'cast_fail', 'ts': ts, 'reason': 'interrupt', 'spell': cim.group(1)}
    cbm = RE_CAST_BLOCKED.match(text)
    if cbm:
        return {'type': 'cast_fail', 'ts': ts, 'reason': 'blocked', 'spell': cbm.group(1),
                'target': cbm.group(2) or 'you', 'blocker': cbm.group(3)}
    if RE_CAST_SAVE.match(text):
        return {'type': 'cast_save', 'ts': ts}

    # kills / deaths
    km = RE_YOU_KILL.match(text)
    if km:
        return {'type': 'kill', 'ts': ts, 'target': km.group(1)}
    ydm = RE_YOU_DIED.match(text)
    if ydm:
        return {'type': 'player_death', 'ts': ts, 'killer': ydm.group(1)}
    # ── mob deaths + crowd control ──
    # Every shape here opens with an arbitrary mob name, so the patterns cannot be
    # prefix-anchored and Python has to backtrack the whole line to reject one. A single
    # substring test gates the group instead — worth roughly 25 s over an 80 MB backfill.
    if ' has been ' in text:
        # generic death — after RE_YOU_DIED, which is a special case of this shape.
        # Feeds pet/ally death alerts and clears the dead mob off the CC board.
        sbm = RE_SLAIN_BY.match(text)
        if sbm:
            return {'type': 'mob_slain', 'ts': ts, 'victim': sbm.group(1),
                    'killer': sbm.group(2)}
        mzm = RE_MOB_MEZ.match(text)
        if mzm:
            return {'type': 'mob_cc', 'ts': ts, 'mob': mzm.group(1), 'cc': 'mez',
                    'state': 'on'}
        mem = RE_MOB_ENTHRALL.match(text)
        if mem:
            return {'type': 'mob_cc', 'ts': ts, 'mob': mem.group(1), 'cc': 'mez',
                    'state': 'on', 'spell': 'Enthrall'}
        mcm = RE_MOB_CHARM.match(text)
        if mcm:
            return {'type': 'mob_cc', 'ts': ts, 'mob': mcm.group(1), 'cc': 'charm',
                    'state': 'on'}
        msn = RE_MOB_ENSNARE.match(text)
        if msn:
            return {'type': 'mob_cc', 'ts': ts, 'mob': msn.group(1), 'cc': 'snare',
                    'state': 'on'}
        mwm = RE_MOB_WAKE.match(text)
        if mwm:
            # the enchanter's panic button: something woke a mezzed add
            return {'type': 'mob_cc', 'ts': ts, 'mob': mwm.group(1), 'cc': 'mez',
                    'state': 'off', 'by': mwm.group(2), 'broke': True}
    if ' is stunned by ' in text:
        mst = RE_MOB_STUN.match(text)
        if mst:
            return {'type': 'mob_cc', 'ts': ts, 'mob': mst.group(1), 'cc': 'stun',
                    'state': 'on', 'spell': mst.group(2)}

    # healing
    hm = RE_HEAL_OT.match(text)
    if hm:
        return {'type': 'heal', 'ts': ts, 'healer': hm.group(1), 'target': hm.group(2),
                'amount': int(hm.group(4) or hm.group(3)), 'spell': hm.group(5), 'is_hot': True}
    hm = RE_HEAL.match(text)
    if hm:
        return {'type': 'heal', 'ts': ts, 'healer': hm.group(1), 'target': hm.group(2),
                'amount': int(hm.group(4) or hm.group(3)), 'spell': hm.group(5), 'is_hot': False}

    # player melee
    mm = RE_YOU_MELEE.match(text)
    if mm:
        return {'type': 'damage', 'ts': ts, 'attacker': 'player',
                'target': mm.group(2), 'amount': int(mm.group(3)),
                'dmg_type': 'melee', 'spell': None, 'verb': _norm_verb(mm.group(1)),
                **_flags(mm.group(4))}

    # player direct spell
    sm = RE_YOU_SPELL.match(text)
    if sm:
        return {'type': 'damage', 'ts': ts, 'attacker': 'player',
                'target': sm.group(1), 'amount': int(sm.group(2)),
                'dmg_type': 'spell', 'spell': sm.group(3), 'verb': 'spell', **_NO_FLAGS}

    # player DoT tick
    dm = RE_YOU_DOT.match(text)
    if dm:
        return {'type': 'damage', 'ts': ts, 'attacker': 'player',
                'target': dm.group(1), 'amount': int(dm.group(2)),
                'dmg_type': 'dot', 'spell': dm.group(3), 'verb': 'dot', **_NO_FLAGS}

    # player miss / target avoided
    ym = RE_YOU_MISS.match(text)
    if ym:
        avoid = ym.group('avoid')
        outcome = _AVOID_NORMALIZE.get(avoid, 'miss') if avoid else (
            'absorb' if ym.group('absorber') else 'miss')
        return {'type': 'miss', 'ts': ts, 'attacker': 'player',
                'target': ym.group(2), 'verb': _norm_verb(ym.group(1)),
                'outcome': outcome, **_flags(ym.groups()[-1])}

    # player damage shield / proc
    dso = RE_DS_OUT.match(text)
    if dso:
        return {'type': 'damage', 'ts': ts, 'attacker': 'player',
                'target': dso.group(1), 'amount': int(dso.group(3)),
                'dmg_type': 'ds', 'spell': dso.group(2), 'verb': 'ds', **_NO_FLAGS}

    # pet damage (only if pet name is known)
    if pet_name:
        phm = RE_PET_MELEE.match(text)
        if phm and phm.group(1) == pet_name:
            return {'type': 'damage', 'ts': ts, 'attacker': 'pet',
                    'target': phm.group(3), 'amount': int(phm.group(4)),
                    'dmg_type': 'melee', 'spell': None, 'verb': _norm_verb(phm.group(2)),
                    **_flags(phm.group(5))}
        psm = RE_PET_SPELL.match(text)
        if psm and psm.group(1) == pet_name:
            return {'type': 'damage', 'ts': ts, 'attacker': 'pet',
                    'target': psm.group(2), 'amount': int(psm.group(3)),
                    'dmg_type': 'spell', 'spell': psm.group(4), 'verb': 'spell', **_NO_FLAGS}
        pmm = RE_PET_MISS.match(text)
        if pmm and pmm.group(1) == pet_name:
            avoid = pmm.group('avoid')
            outcome = _AVOID_NORMALIZE.get(avoid, 'miss') if avoid else (
                'absorb' if pmm.group('absorber') else 'miss')
            return {'type': 'miss', 'ts': ts, 'attacker': 'pet',
                    'target': pmm.group(3), 'verb': _norm_verb(pmm.group(2)),
                    'outcome': outcome, **_flags(pmm.groups()[-1])}

    # damage taken — melee (YOU in caps per EQ log format)
    tym = RE_MELEE_YOU.match(text)
    if tym:
        return {'type': 'damage_taken', 'ts': ts, 'source': tym.group(1), 'victim': 'player',
                'amount': int(tym.group(3)), 'dmg_type': 'melee', 'spell': None,
                'verb': _norm_verb(tym.group(2)), **_flags(tym.group(4))}

    # damage taken — spell/DoT
    tys = RE_SPELL_YOU.match(text)
    if tys:
        return {'type': 'damage_taken', 'ts': ts, 'source': tys.group(1), 'victim': 'player',
                'amount': int(tys.group(2)), 'dmg_type': 'spell', 'spell': tys.group(3),
                'verb': 'spell', **_NO_FLAGS}

    # damage taken — damage shield reflected onto you
    dsi = RE_DS_IN.match(text)
    if dsi:
        return {'type': 'damage_taken', 'ts': ts, 'source': dsi.group(1), 'victim': 'player',
                'amount': int(dsi.group(3)), 'dmg_type': 'ds', 'spell': dsi.group(2),
                'verb': 'ds', **_NO_FLAGS}

    # mob attacked you and missed / you avoided it
    mym = RE_MISS_YOU.match(text)
    if mym:
        avoid = mym.group('avoid')
        outcome = _AVOID_NORMALIZE.get(avoid, 'miss') if avoid else 'miss'
        if not avoid and 'magical skin' in text:
            outcome = 'absorb'
        return {'type': 'miss_taken', 'ts': ts, 'source': mym.group(1),
                'verb': _norm_verb(mym.group(2)), 'outcome': outcome,
                **_flags(mym.groups()[-1])}

    # other group members' damage to mobs (only if currently grouped with them)
    if group_members:
        gom = RE_OTHER_MELEE.match(text)
        if gom and gom.group(1) in group_members:
            return {'type': 'damage', 'ts': ts, 'attacker': gom.group(1),
                    'target': gom.group(3), 'amount': int(gom.group(4)),
                    'dmg_type': 'melee', 'spell': None, 'verb': _norm_verb(gom.group(2)),
                    **_flags(gom.group(5))}
        gos = RE_OTHER_SPELL.match(text)
        if gos and gos.group(1) in group_members:
            return {'type': 'damage', 'ts': ts, 'attacker': gos.group(1),
                    'target': gos.group(2), 'amount': int(gos.group(3)),
                    'dmg_type': 'spell', 'spell': gos.group(4), 'verb': 'spell', **_NO_FLAGS}
        # A member's swing that did not land. Emitted with the same shape as your own and
        # the pet's misses, so the accuracy maths downstream needs no new branch.
        gmm = RE_OTHER_MISS.match(text)
        if gmm and gmm.group(1) in group_members and gmm.group(1) != pet_name:
            avoid = gmm.group('avoid')
            outcome = _AVOID_NORMALIZE.get(avoid, 'miss') if avoid else (
                'absorb' if gmm.group('absorber') else 'miss')
            return {'type': 'miss', 'ts': ts, 'attacker': gmm.group(1),
                    'target': gmm.group(3), 'verb': _norm_verb(gmm.group(2)),
                    'outcome': outcome, **_flags(gmm.groups()[-1])}

    # pet damage shield (checked after group damage so a grouped player named like the pet
    # is not misattributed)
    if pet_name:
        dsp = RE_DS_OTHER.match(text)
        if dsp and dsp.group(2) == pet_name:
            return {'type': 'damage', 'ts': ts, 'attacker': 'pet',
                    'target': dsp.group(1), 'amount': int(dsp.group(4)),
                    'dmg_type': 'ds', 'spell': dsp.group(3), 'verb': 'ds', **_NO_FLAGS}

    # A group member's damage shield. Checked after the pet's so that a member who happens
    # to share the pet's name is still counted as the pet, matching every other branch.
    # Worth 293,757 damage over 22,676 hits on the reference log, all of it previously
    # dropped on the floor -- one member's shield alone out-damaged several members' swings.
    if group_members:
        dsa = RE_DS_OTHER.match(text)
        if dsa and dsa.group(2) in group_members and dsa.group(2) != pet_name:
            return {'type': 'damage', 'ts': ts, 'attacker': dsa.group(2),
                    'target': dsa.group(1), 'amount': int(dsa.group(4)),
                    'dmg_type': 'ds', 'spell': dsa.group(3), 'verb': 'ds', **_NO_FLAGS}

    # melee damage taken by an ally — the pet, or a current group member.
    # Sits OUTSIDE `if pet_name:` on purpose: a caster in a group with no pet out still
    # wants their group's incoming damage, and the old nesting silently dropped all of it.
    # Still after the group-damage block above, so a member's own OUTGOING swing at a
    # single-word-named mob ("Harsamina slashes Gynok…") is read as damage dealt, not as
    # damage landing on someone called Gynok.
    tpm = RE_MELEE_PET.match(text)
    if tpm:
        hit = tpm.group(3)
        victim = ('pet' if pet_name and hit == pet_name
                  else hit if group_members and hit in group_members else None)
        if victim:
            return {'type': 'damage_taken', 'ts': ts, 'source': tpm.group(1), 'victim': victim,
                    'amount': int(tpm.group(4)), 'dmg_type': 'melee', 'spell': None,
                    'verb': _norm_verb(tpm.group(2)), **_flags(tpm.group(5))}

    # resists
    rym = RE_RESIST_YOU.match(text)
    if rym:
        return {'type': 'resist_self_success', 'ts': ts, 'mob': rym.group(1), 'spell': rym.group(2)}
    rsm = RE_RESIST_SELF.match(text)
    if rsm:
        return {'type': 'resist', 'ts': ts, 'mob': 'Unknown', 'spell': rsm.group(1)}
    rm = RE_RESIST_MOB.match(text)
    if rm:
        return {'type': 'resist', 'ts': ts, 'mob': rm.group(1), 'spell': rm.group(2)}

    # loot — merchant sales first, so their coin is not mistaken for kill income
    vsm = RE_VENDOR_SALE.match(text)
    if vsm:
        return {'type': 'vendor_sale', 'ts': ts, 'amount': vsm.group(1),
                'vendor': vsm.group(2), 'item': vsm.group(3),
                'copper': _parse_coin(vsm.group(1))}

    dlm = RE_LOOT_DEPOT.match(text)
    if dlm:
        return {'type': 'loot', 'ts': ts, 'item': dlm.group(2), 'source': dlm.group(3),
                'qty': int(dlm.group(1) or 1), 'copper': None}

    for pat in (RE_LOOT_DASH, RE_LOOT_PLAIN):
        lm = pat.match(text)
        if not lm:
            continue
        item, source = _split_loot(lm.group(1))
        copper = _parse_coin(item)
        # a pure coin payout is money, not an item — emitting it as loot buried the
        # real drops under thousands of "7 silver and 2 copper" rows
        if copper is not None:
            return {'type': 'coin', 'ts': ts, 'copper': copper, 'source': source}
        return {'type': 'loot', 'ts': ts, 'item': item, 'source': source, 'copper': None}

    # ── faction ───────────────────────────────────────────────────────────────
    fam = RE_FACTION_ADJ.match(text)
    if fam:
        return {'type': 'faction', 'ts': ts, 'faction': fam.group(1),
                'delta': int(fam.group(2))}
    fcm = RE_FACTION_CAP.match(text)
    if fcm:
        # 'better' means already maxed ally, 'worse' already bottomed enemy
        return {'type': 'faction_capped', 'ts': ts, 'faction': fcm.group(1),
                'direction': fcm.group(2)}

    # ── tradeskills ───────────────────────────────────────────────────────────
    tsm = RE_TS_MADE.match(text)
    if tsm:
        return {'type': 'craft', 'ts': ts, 'item': tsm.group(1), 'ok': True}
    tsf = RE_TS_FAILED.match(text)
    if tsf:
        return {'type': 'craft', 'ts': ts, 'item': tsf.group(1), 'ok': False}
    if RE_TS_CAPPED.match(text):
        # No recipe name on this line: it follows the combine it refers to, so the server
        # attaches it to the last craft rather than guessing here.
        return {'type': 'craft_capped', 'ts': ts}
    dcm = RE_DEPOT_CONSUME.match(text)
    if dcm:
        return {'type': 'depot_consume', 'ts': ts, 'qty': int(dcm.group(1)),
                'item': dcm.group(2), 'left': int(dcm.group(3))}

    # unrecognized buff-shaped emote — surfaced so BUFF_EMOTES can be grown from real data
    if RE_EMOTE_CANDIDATE.match(text):
        return {'type': 'emote_unknown', 'ts': ts, 'text': text}

    return None
