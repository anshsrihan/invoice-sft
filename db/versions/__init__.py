"""Ordered registry of database migrations."""

from db.versions.m001_phase1_foundation import upgrade as m001_upgrade

MIGRATIONS = [
    (1, "phase1_foundation", m001_upgrade),
]
