# """
# ==============================================================================
# FILE: database.py
# ROLE: The Memory
# DESCRIPTION:
# Handles all SQLite database operations. It remembers which items have 
# already been searched so we don't spam the API, and tracks "strikes" 
# for bad torrents before the cleaner deletes them.
# ==============================================================================
# """

import os
import sqlite3
import logging
from datetime import datetime

# Import the dynamic config manager and the static DB_PATH
from config import cfg, DB_PATH

# Initialize the logger for this specific module
logger = logging.getLogger(__name__)

# Setup logging so we can see what the script is doing in the console
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
    level=getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
)

def init_db():
    """
    Creates a small SQLite database to remember what was already searched 
    and to keep track of torrent 'strikes' (warnings before deletion).
    """
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sonarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS radarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS lidarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS bazarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS torrent_strikes (hash TEXT PRIMARY KEY, strikes INTEGER, last_checked TEXT, reason TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

# --- Database Helper Functions ---
def get_searched_ids(table_name):
    """Gets all the IDs we already searched for from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"SELECT id FROM {table_name}")
        rows = c.fetchall()
        conn.close()
        return {row[0] for row in rows}
    except Exception:
        return set()

def add_searched_id(table_name, item_id):
    """Saves a searched ID into the database so we do not search it again."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"INSERT OR IGNORE INTO {table_name} (id, timestamp) VALUES (?, ?)", (item_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

def wipe_table(table_name):
    """Deletes all records from a specific table (Resets the memory)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"DELETE FROM {table_name}")
        conn.commit()
        conn.close()
        logger.warning(f"Cycle Reset: Wiped memory table {table_name}")
    except Exception:
        pass

def update_strike(torrent_hash, reason):
    """Adds a strike to a bad torrent. Returns the current number of strikes."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT strikes FROM torrent_strikes WHERE hash=?", (torrent_hash,))
        row = c.fetchone()
        if row:
            new_strikes = row[0] + 1
            c.execute("UPDATE torrent_strikes SET strikes=?, last_checked=?, reason=? WHERE hash=?",
                      (new_strikes, datetime.now().isoformat(), reason, torrent_hash))
        else:
            new_strikes = 1
            c.execute("INSERT INTO torrent_strikes (hash, strikes, last_checked, reason) VALUES (?, ?, ?, ?)",
                      (torrent_hash, new_strikes, datetime.now().isoformat(), reason))
        conn.commit()
        conn.close()
        return new_strikes
    except Exception:
        return 0

def get_strikes(torrent_hash):
    """Checks how many strikes a torrent currently has."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT strikes FROM torrent_strikes WHERE hash=?", (torrent_hash,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0

def clear_strikes(torrent_hash):
    """Removes a torrent from the strikes database if it becomes healthy again."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM torrent_strikes WHERE hash=?", (torrent_hash,))
        conn.commit()
        conn.close()
    except Exception:
        pass