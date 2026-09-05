"""
SQLite connection and schema. One file, WAL mode, created on first start.

Rebuilt from inventory.json at every boot, so the listings table is a cache
and the JSON file stays the source of truth for the inventory.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

LISTING_COLUMNS = (
    "id",
    "source_sheet",
    "source_row",
    "make",
    "model",
    "trim",
    "year",
    "title",
    "description_raw",
    "description_clean",
    "english_summary",
    "keywords_en",
    "photo_url",
    "price_aed",
    "monthly_aed",
    "price_vat_status",
    "down_payment_pct",
    "mileage_km",
    "is_brand_new",
    "exterior_color",
    "interior_color",
    "body_type",
    "regional_spec",
    "fuel_type",
    "transmission",
    "seats",
    "has_warranty",
    "warranty_text",
    "service_contract",
    "is_export_only",
    "is_dubizzle_managed",
    "language",
    "truncated",
    "description_quality",
    "dealer_name",
    "provenance_json",
    "dealer_contact_json",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS listings (
  id TEXT PRIMARY KEY, source_sheet TEXT, source_row INTEGER, make TEXT, model TEXT, trim TEXT,
  year INTEGER, title TEXT, description_raw TEXT, description_clean TEXT, english_summary TEXT,
  keywords_en TEXT, photo_url TEXT, price_aed INTEGER, monthly_aed INTEGER, price_vat_status TEXT,
  down_payment_pct INTEGER, mileage_km INTEGER, is_brand_new INTEGER, exterior_color TEXT,
  interior_color TEXT, body_type TEXT, regional_spec TEXT, fuel_type TEXT, transmission TEXT,
  seats INTEGER, has_warranty INTEGER, warranty_text TEXT, service_contract INTEGER,
  is_export_only INTEGER, is_dubizzle_managed INTEGER, language TEXT, truncated INTEGER,
  description_quality TEXT, dealer_name TEXT, provenance_json TEXT, dealer_contact_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_listings_make_model ON listings(make, model);
CREATE INDEX IF NOT EXISTS ix_listings_price ON listings(price_aed);

CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
  id UNINDEXED, make, model, trim, title, english_summary, keywords_en, description_clean,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL,
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_name_key ON users(name_key);

CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
  last_active_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', turn_counter INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, turn INTEGER NOT NULL,
  role TEXT NOT NULL, blob_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS session_context (
  session_id TEXT PRIMARY KEY, shown_json TEXT NOT NULL DEFAULT '[]', focus_id TEXT,
  pending_booking_json TEXT, summary_text TEXT, summary_through_turn INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS preference_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
  source TEXT NOT NULL, session_id TEXT, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pref_user ON preference_events(user_id, id);

CREATE TABLE IF NOT EXISTS liked_cars (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, listing_id TEXT NOT NULL,
  snapshot_json TEXT NOT NULL, session_id TEXT, ts TEXT NOT NULL,
  UNIQUE(user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS search_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, session_id TEXT, raw_query TEXT NOT NULL,
  parsed_filters_json TEXT NOT NULL, result_count INTEGER NOT NULL, ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_user ON search_history(user_id, id);

CREATE TABLE IF NOT EXISTS bookings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL,
  listing_id TEXT NOT NULL, slot_start TEXT NOT NULL, slot_end TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed', created_at TEXT NOT NULL, cancelled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_listing_slot ON bookings(listing_id, slot_start) WHERE status = 'confirmed';
CREATE UNIQUE INDEX IF NOT EXISTS ux_booking_user_slot ON bookings(user_id, slot_start) WHERE status = 'confirmed';

CREATE TABLE IF NOT EXISTS leads (
  lead_id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE, data_json TEXT NOT NULL,
  status TEXT NOT NULL, qualification_reason TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turn_traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, turn INTEGER NOT NULL,
  request_id TEXT NOT NULL, trace_json TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(session_id, turn)
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session_id TEXT, turn INTEGER, n INTEGER,
  model TEXT NOT NULL, reasoning TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
  latency_ms INTEGER, finish_reason TEXT, cassette_hit INTEGER NOT NULL DEFAULT 0, purpose TEXT
);

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT NOT NULL, user_id TEXT NOT NULL, envelope_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (key, user_id)
);

CREATE TABLE IF NOT EXISTS rate_counters (
  scope TEXT NOT NULL, window_start TEXT NOT NULL, count INTEGER NOT NULL,
  PRIMARY KEY (scope, window_start)
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
            conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()
