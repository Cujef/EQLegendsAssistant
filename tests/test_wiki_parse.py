"""wiki_parse suites: fixtures are TRIMMED live-page wikitext (fetched
2026-08-28 from eqlwiki.com: Singing_Short_Sword, Incandescent_Mask,
Bard_Epic_Quest, Bat_Fur_Quest, Recommended_Levels_and_ZEM_List, Statistics)."""

ITEM_SSS = """{{Epics Era}}

<onlyinclude>{{Itempage
|notes       = {{Item Lore|Singing Short Sword}}

The effect (Dance of the Blade) is a full party buff [[Players:EQLive_Timeline#Development_timeline|October 2001]]:<br>

Works in the offhand at {{Era | Chardok}}
|itemname    = Singing Short Sword
|lucy_img_ID = 882
|statsblock  =

MAGIC ITEM  LORE ITEM  NO DROP  <br>
Slot: PRIMARY SECONDARY<br>
Skill: 1H Slashing  Atk Delay: 26<br>
All Instrument Types<br>
DMG: 16 <br>
STR: +15  DEX: +10  STA: +5  CHA: +20  HP: +100<br>
SV FIRE: +10  SV DISEASE: +10  SV COLD: +10  SV MAGIC: +10  SV POISON: +10<br>
Required level of 46.<br>
Effect:  [[Dance of the Blade|<span class='itemeff'>Dance of the Blade</span>]] (Combat, Casting Time: Instant) at Level 46<br>
WT: 2.0  Size: MEDIUM<br>
Class: BRD<br>
Race: ALL<br>

|relatedquests =


}}</onlyinclude>

[[Category:Bard Equipment]]
[[Category:Primary]]"""

ITEM_MASK = """{{Temple Era}}

<onlyinclude>{{Itempage
|notes       =
|itemname    = Incandescent Mask
|lucy_img_ID = 771
|statsblock  =
MAGIC ITEM  LORE ITEM<br>
Slot: FACE<br>
AC: 3<br>
CHA: +7  INT: +5<br>
WT: 0.4  Size: SMALL<br>
Class: MNK ENC<br>
Race: ALL<br>
|focus_effect = Summoning Haste II
|relatedquests =

* [[Incandescent Armor Quests|Incandescent Mask]]

}}</onlyinclude>

[[Category:Focus Items]]
[[Category:Quest Items]]"""

QUEST_EPIC = """{{Epics Era}}

[[File:epic.jpg|200px|thumb|Singing Short Sword]]
__NOTOC__
{| class="questTopTable"
! ''' Start Zone: '''
| [[Dreadlands]]
|-
! ''' Quest Giver: '''
| Baldric Slezaf
|-
! ''' Recommended Level: '''
| 46+
|-
! ''' Classes: '''
| [[Bard]]
|-
! ''' Related Zones: '''
| Various
|}

== Reward ==

<ul><li> {{:Singing Short Sword}}
</li></ul>

== Checklist ==

{{CheckboxList}}
==== Maestro's Symphony Page 24 Top ====

* Talk to [[Konia Swiftfoot]] in [[Western Karana]] (guard tower #4), receive a [[Torch of Misty]]
* Give the torch to [[Fajio Knejo]] in [[Misty Thicket]], receive [[Torch of Ro]]
* Give the ring to [[Konia Swiftfoot]] in [[Western Karana|W Karana]], receive [[Maestro's Symphony Page 24 Top]]

==== Maestro's Symphony Page 25 ====
* Kill [36][[Blackwing]] in [[Rathe Mountains]], loot [[Onyx Drake Gut]]
* Give all the guts to [[Kelkim Menkia]] in [[South Karana]], receive [[Maestro's Symphony Page 25]]
{{End}}"""

QUEST_PROSE = """{{Classic Era}}
[[File:npc_caleah_herblender.png|frame|Caleah Herblender]]
{| class="questTopTable"
! ''' Start Zone: '''
| [[Qeynos|South Qeynos]]
|-
! ''' Quest Giver: '''
| [[Caleah Herblender]]
|-
! ''' Minimum Level: '''
| 2
|-
! ''' Classes: '''
| All
|-
! ''' Related NPCs: '''
| newbie mobs, [[Drawna Opimsor]]
|}

== Walkthrough ==

'''Faction: Order of Three, minimum Indifferent or better is required.'''

[[Caleah Herblender]] may be found inside the Herb Jar. Your Location is 303.76, -554.90, 3.36

: Caleah Herblender says 'Drawna. Are we all out of [[Bat Fur]] again?'

You say, 'What [[fire beetle eye]]?'

All three items are common drops from the mobs in the newbie yard outside the Qeynos north gate.  Hand them in in this specific order: Bat Fur, Bat Fur, Rat Whisker, Fire Beetle Eye.

<div class="facblock">
* Your faction standing with [[Order of Three]] got better.
* Your faction standing with [[Bloodsabers]] got worse.
</div>
{{exp}}

[[Category:Quests]]
[[Category:All Classes Quests]]"""

ZEM_GUIDE = """= Recommended Hunting Levels =
== Antonica ==

{| class="wikitable sortable sticky-header" style="width: 100%;"
|- style="position: sticky; top: 0; background-color: #eaecf0; z-index: 2;"
! style="width: 15%;"| Zone
! style="width: 5%;" | Type
! style="width: 5%;" | Lvl Range
! style=" min-width: 45px;" | 1
! style=" min-width: 45px;" | 5
! style=" min-width: 45px;" | 10
|-
| [[North Qeynos]] || City || 1 - 5 || [[file:lightblueCircle.png]] || [[file:goldCircle.png]] || [[file:lightpinkCircle.png]]
|-
| [[Blackburrow]] {{#vardefine:zem|119}} || Dungeon || 5 - 15 || || [[file:lightblueCircle.png]] || [[file:orangeRing.png]]
|-
| [[Sleeper's Tomb]] || Dungeon || 60+ || || ||
|}"""

STATS_PAGE = """{{Cleanup}}

== Primary Stats ==
{| class="eoTable2 sortable" style="text-align:center"
|-
! Race !! Str !! Sta
|-
| style="text-align: left"| '''[[Barbarian]]''' || 103 || 95
|}

===Strength (STR)===

Affects: Attack Power, Weight Limit
*Max (hard-cap): 255

===Wisdom (WIS)===

*Max (hard-cap): 255
*Soft-cap: 200
"""


def run(check):
    _markup(check)
    _effects(check)
    _items(check)
    _quests(check)
    _guides(check)
    _malformed(check)


def _markup(check):
    from app.sync.wiki_parse import extract_links, strip_markup, title_to_url

    check('markup: [[A|B]] -> B', strip_markup('see [[Foo|Bar]] now') == 'see Bar now')
    check('markup: [[A]] -> A', strip_markup('kill [[Blackwing]]') == 'kill Blackwing')
    check('markup: span in link',
          strip_markup("[[Dance|<span class='x'>Dance</span>]]") == 'Dance')
    check('markup: quotes stripped', strip_markup("'''bold''' and ''it''") == 'bold and it')
    check('markup: leaf template dropped', strip_markup('a {{exp}} b') == 'a b')
    check('markup: links skip namespaces',
          extract_links('[[Bat Fur]] [[File:x.png]] [[Category:Quests]] [[Bat Fur]]')
          == ['Bat Fur'])
    check('markup: url underscores',
          title_to_url('Bard Epic Quest') == 'https://eqlwiki.com/Bard_Epic_Quest')
    check('markup: url apostrophe kept',
          title_to_url("Ak'Anon Quests") == "https://eqlwiki.com/Ak'Anon_Quests")


def _effects(check):
    from app.sync.wiki_parse import effect_family_tier, parse_effect_line

    check('tier: Improved Damage II',
          effect_family_tier('Improved Damage II') == ('Improved Damage', 2))
    check('tier: IX', effect_family_tier('Cleave IX') == ('Cleave', 9))
    check('tier: none', effect_family_tier('Dance of the Blade')
          == ('Dance of the Blade', None))
    check('tier: X', effect_family_tier('Haste X') == ('Haste', 10))

    e = parse_effect_line("Effect: [[Dance of the Blade|<span class='i'>Dance of the "
                          "Blade</span>]] (Combat, Casting Time: Instant) at Level 46")
    check('effect: combat -> proc', e and e['effect_type'] == 'proc'
          and e['effect_name'] == 'Dance of the Blade', e)
    e = parse_effect_line('Effect: Word of Vigor (Any Slot/Can Equip, Casting Time: 6.0)')
    check('effect: casting time -> click', e and e['effect_type'] == 'click', e)
    e = parse_effect_line('Effect: Sound of the Storm (Worn)')
    check('effect: worn paren', e and e['effect_type'] == 'worn', e)
    e = parse_effect_line('Effect: Cure Disease (Must Equip, Casting Time: Instant)')
    check('effect: must equip -> worn', e and e['effect_type'] == 'worn', e)
    e = parse_effect_line('Focus Effect: Improved Damage II')
    check('effect: focus prefix', e and e['effect_type'] == 'focus'
          and e['effect_tier'] == 2, e)
    check('effect: non-effect line', parse_effect_line('DMG: 16') is None)


def _items(check):
    from app.sync.wiki_parse import parse_itempage

    it = parse_itempage(ITEM_SSS)
    check('item: parsed', it is not None)
    check('item: name', it['itemname'] == 'Singing Short Sword')
    check('item: icon', it['icon'] == 882, it['icon'])
    check('item: dmg/delay', it['dmg'] == 16 and it['delay'] == 26,
          (it['dmg'], it['delay']))
    check('item: skill', it['skill'] == '1H Slashing')
    check('item: flags', it['flags'] == ['MAGIC ITEM', 'LORE ITEM', 'NO DROP'])
    check('item: stats dict',
          it['stats'].get('STR') == 15 and it['stats'].get('CHA') == 20, it['stats'])
    check('item: hp promoted', it['hp'] == 100)
    check('item: resists', it['resists'].get('FIRE') == 10
          and it['resists'].get('POISON') == 10, it['resists'])
    check('item: class/race', it['class_text'] == 'BRD' and it['race_text'] == 'ALL')
    check('item: slot', it['slot_text'] == 'PRIMARY SECONDARY')
    check('item: required level', it['required_level'] == 46)
    check('item: wt/size', it['wt'] == 2.0 and it['size'] == 'MEDIUM')
    check('item: proc effect', len(it['effects']) == 1
          and it['effects'][0]['effect_type'] == 'proc'
          and it['effects'][0]['effect_name'] == 'Dance of the Blade', it['effects'])

    m = parse_itempage(ITEM_MASK)
    check('item: mask ac', m['ac'] == 3)
    check('item: focus_effect param -> focus',
          any(e['effect_type'] == 'focus' and e['effect_name'] == 'Summoning Haste II'
              and e['effect_tier'] == 2 for e in m['effects']), m['effects'])
    check('item: mask no dmg', m['dmg'] is None and m['delay'] is None)


def _quests(check):
    from app.sync.wiki_parse import parse_quest

    q = parse_quest(QUEST_EPIC)
    check('quest: top table seen', q['has_top_table'])
    check('quest: start zone', q['start_zone'] == 'Dreadlands')
    check('quest: giver', q['quest_giver'] == 'Baldric Slezaf')
    check('quest: 46+ level', q['level_min'] == 46 and q['level_max'] is None,
          (q['level_min'], q['level_max']))
    check('quest: classes', q['classes'] == ['Bard'])
    check('quest: step count', len(q['steps']) == 5, len(q['steps']))
    check('quest: section prefix',
          q['steps'][0].startswith("Maestro's Symphony Page 24 Top — Talk to Konia"),
          q['steps'][0])
    check('quest: reward list skipped',
          not any('Singing Short Sword' in s for s in q['steps']))
    check('quest: mentions include items',
          'Torch of Misty' in q['item_mentions'] and 'Onyx Drake Gut' in q['item_mentions'])
    check('quest: top-table links not mentions', 'Dreadlands' not in q['item_mentions'])

    p = parse_quest(QUEST_PROSE)
    check('quest: piped zone display', p['start_zone'] == 'South Qeynos')
    check('quest: min level row', p['level_min'] == 2)
    check('quest: classes All', p['classes'] == ['All'])
    check('quest: prose fallback steps', len(p['steps']) == 3, p['steps'])
    check('quest: dialogue excluded',
          not any("says '" in s or 'You say' in s for s in p['steps']), p['steps'])
    check('quest: faction bullets excluded',
          not any('faction standing' in s for s in p['steps']))
    check('quest: prose mentions', 'Bat Fur' in p['item_mentions']
          and 'fire beetle eye' in p['item_mentions'], p['item_mentions'])


def _guides(check):
    from app.sync.wiki_parse import (parse_generic_guide, parse_statistics,
                                     parse_zem_guide, redirect_target)

    rows = parse_zem_guide(ZEM_GUIDE)
    check('zem: row count', len(rows) == 3, len(rows))
    r = rows[0]
    check('zem: row shape',
          set(r) == {'region', 'zone', 'level_min', 'level_max', 'zem', 'ratings'}, r)
    check('zem: zone/region', r['zone'] == 'North Qeynos' and r['region'] == 'Antonica')
    check('zem: level range', r['level_min'] == 1 and r['level_max'] == 5)
    check('zem: ratings mapped', r['ratings'] == {'1': 'efficient', '5': 'inefficient',
                                                  '10': 'not recommended'}, r['ratings'])
    check('zem: vardefine picked up', rows[1]['zem'] == 119, rows[1])
    check('zem: 60+ range', rows[2]['level_min'] == 60 and rows[2]['level_max'] == 60)

    st = parse_statistics(STATS_PAGE)
    caps = {c['stat']: c['cap'] for c in st['caps']}
    check('stats: hard caps', caps.get('str') == 255 and caps.get('wis') == 255, caps)
    check('stats: soft cap', caps.get('wis_soft') == 200, caps)
    check('stats: no phantom caps', 'sta' not in caps, caps)
    check('stats: race table row', any(
        row.get('Race') == 'Barbarian' and row.get('Str') == '103'
        for s in st['sections'] for row in s.get('rows', [])), st['sections'][:1])

    g = parse_generic_guide(ZEM_GUIDE)
    check('guide: generic sections', len(g['sections']) == 1
          and g['sections'][0]['rows'], g['sections'][:1])
    check('guide: redirect detected',
          redirect_target('#redirect [[Category:Focus Effects]]')
          == 'Category:Focus Effects')
    check('guide: non-redirect', redirect_target(ITEM_SSS) is None)


def _malformed(check):
    from app.sync.wiki_parse import (parse_generic_guide, parse_itempage,
                                     parse_quest, parse_statistics,
                                     parse_template, parse_zem_guide)

    check('malformed: non-item page -> None', parse_itempage('just some [[prose]]') is None)
    check('malformed: unterminated template -> None',
          parse_itempage('{{Itempage |itemname = Broken') is None)
    check('malformed: empty itemname -> None',
          parse_itempage('{{Itempage |itemname = |statsblock = AC: 3}}') is None)
    q = parse_quest('')
    check('malformed: empty quest no crash',
          q['steps'] == [] and not q['has_top_table'], q)
    q = parse_quest('{| class="questTopTable"\n! broken')
    check('malformed: unterminated quest table', isinstance(q, dict))
    check('malformed: zem on junk', parse_zem_guide('*junk\nmore junk') == [])
    check('malformed: stats on junk', parse_statistics('junk')['caps'] == [])
    check('malformed: guide on empty', parse_generic_guide('')['sections'] == [])
    check('malformed: template None input', parse_template('', 'Itempage') is None)
