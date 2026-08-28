"""Aggregations shared by the importer (M3) and the live tailer (M4).

Contract: an Aggregator instance consumes ext_parser events and flushes
per-character rows into skill_levels/level_history/aa_ledger/deaths/highlights.
Shared so live play keeps all-time stats current after the initial import.
"""
