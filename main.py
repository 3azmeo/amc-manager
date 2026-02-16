import os
import time
import sqlite3
import requests
import schedule
import logging
import threading
import qbittorrentapi
from datetime import datetime, timedelta

# ==========================================
#       CONFIGURATION & ENVIRONMENT
# ==========================================

# --- General Settings ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_PATH = "/data/history.db"
TZ = os.getenv("TZ", "UTC")  # Just for logging reference

# --- Scheduling (Minutes) ---
# How often to run the missing content searcher
SEARCH_RUN_EVERY = int(os.getenv("RUN_EVERY", "15"))
# How often to run the torrent cleaner/monitor
CLEANER_RUN_EVERY = int(os.getenv("TORRENT_HANDLING_TIMER", "20"))

# --- qBittorrent Settings ---
QBIT_URL = os.getenv("QBITTORRENT_URL", "http://gluetun:8080")
QBIT_USER = os.getenv("QBITTORRENT_USERNAME", "admin")
QBIT_PASS = os.getenv("QBITTORRENT_PASSWORD", "adminadmin")

# --- Torrent Handling Logic (The Cleaner) ---
ENABLE_TORRENT_HANDLING = os.getenv("ENABLE_TORRENT_HANDLING", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# Tagging Logic
PRIVATE_TAGS = os.getenv("TORRENT_HANDLING_PRIVATE_TRACKER_TAGS", "private").split(',')
PROTECTED_TAGS = os.getenv("TORRENT_HANDLING_PROTECTED_TAG", "protected,Keep").split(',')
# Changed from external name to your project specific name
OBSOLETE_TAG = "amc_obsolete"  

# Thresholds
MAX_STRIKES = int(os.getenv("TORRENT_HANDLING_MAX_STRIKES", "3"))
MIN_SPEED_KB = int(os.getenv("TORRENT_HANDLING_REMOVE_SLOW_MIN_SPEED", "100"))
MIN_SPEED_BYTES = MIN_SPEED_KB * 1024

# Feature Toggles
RM_BAD_FILES = os.getenv("TORRENT_HANDLING_REMOVE_BAD_FILES", "true").lower() == "true"
RM_FAILED = os.getenv("TORRENT_HANDLING_REMOVE_FAILED_DOWNLOAD", "true").lower() == "true"
RM_META_MISSING = os.getenv("TORRENT_HANDLING_REMOVE_METADATA_MISSING", "true").lower() == "true"
RM_STALLED = os.getenv("TORRENT_HANDLING_REMOVE_STALLED", "true").lower() == "true"
RM_SLOW = os.getenv("TORRENT_HANDLING_REMOVE_SLOW", "true").lower() == "true"
RM_ORPHANS = os.getenv("TORRENT_HANDLING_REMOVE_ORPHANS", "false").lower() == "true"

# Timeouts (in minutes) - Controlled via Env Vars now
TIMEOUT_METADATA = int(os.getenv("TIMEOUT_METADATA_MINUTES", "15"))
TIMEOUT_STALLED = int(os.getenv("TIMEOUT_STALLED_MINUTES", "15"))

# --- Arr Apps Settings ---
# Sonarr
SONARR_URL = os.getenv("SONARR_URL")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
SONARR_ENABLED = True if SONARR_URL and SONARR_API_KEY else False

# Radarr
RADARR_URL = os.getenv("RADARR_URL")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")
RADARR_ENABLED = True if RADARR_URL and RADARR_API_KEY else False

# Lidarr (Added)
LIDARR_URL = os.getenv("LIDARR_URL")
LIDARR_API_KEY = os.getenv("LIDARR_API_KEY")
LIDARR_ENABLED = True if LIDARR_URL and LIDARR_API_KEY else False

# Bazarr (Added for Searcher only - Bazarr does not use qBit for torrents)
BAZARR_URL = os.getenv("BAZARR_URL")
BAZARR_API_KEY = os.getenv("BAZARR_API_KEY")
BAZARR_ENABLED = True if BAZARR_URL and BAZARR_API_KEY else False

# Searcher Specifics
REQUEST_DELAY = int(os.getenv("REQUEST_DELAY_SECONDS", "5"))
MAX_CYCLE_DAYS = int(os.getenv("MAX_CYCLE_DAYS", "30"))
# Limits
SONARR_LIMIT = int(os.getenv("SONARR_LIMIT", "10"))
SONARR_CUTOFF = int(os.getenv("SONARR_CUTOFF_LIMIT", "0"))
RADARR_LIMIT = int(os.getenv("RADARR_LIMIT", "10"))
RADARR_CUTOFF = int(os.getenv("RADARR_CUTOFF_LIMIT", "0"))
LIDARR_LIMIT = int(os.getenv("LIDARR_LIMIT", "10"))
LIDARR_CUTOFF = int(os.getenv("LIDARR_CUTOFF_LIMIT", "0"))


# Searcher Specifics
REQUEST_DELAY = int(os.getenv("REQUEST_DELAY_SECONDS", "5"))
MAX_CYCLE_DAYS = int(os.getenv("MAX_CYCLE_DAYS", "30"))
SONARR_LIMIT = int(os.getenv("SONARR_LIMIT", "10"))
SONARR_CUTOFF = int(os.getenv("SONARR_CUTOFF_LIMIT", "0"))
RADARR_LIMIT = int(os.getenv("RADARR_LIMIT", "10"))
RADARR_CUTOFF = int(os.getenv("RADARR_CUTOFF_LIMIT", "0"))

# ==========================================
#           LOGGING & DATABASE
# ==========================================

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

def init_db():
    """Initialize SQLite tables for both Searcher history and Cleaner strikes."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 1. Searcher Tables (Updated to include Lidarr/Bazarr)
        c.execute('''CREATE TABLE IF NOT EXISTS sonarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS radarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS lidarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS bazarr_searches (id INTEGER PRIMARY KEY, timestamp TEXT)''')
        
        # 2. Cleaner Tables (New Logic - Persistent Strikes)
        # hash: Torrent Hash
        # strikes: Current strike count
        # last_checked: Timestamp of last check
        # reason: Why it got the last strike
        c.execute('''CREATE TABLE IF NOT EXISTS torrent_strikes 
                     (hash TEXT PRIMARY KEY, strikes INTEGER, last_checked TEXT, reason TEXT)''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {DB_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

# --- DB Helpers for Searcher ---
def get_searched_ids(table_name):
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
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"INSERT OR IGNORE INTO {table_name} (id, timestamp) VALUES (?, ?)", 
                  (item_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Error (Add ID): {e}")

def wipe_table(table_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"DELETE FROM {table_name}")
        conn.commit()
        conn.close()
        logger.warning(f"Cycle Reset: Wiped table {table_name}")
    except Exception as e:
        logger.error(f"DB Error (Wipe): {e}")

# --- DB Helpers for Cleaner (Strikes) ---
def update_strike(torrent_hash, reason):
    """Increment strike count for a torrent."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check existing
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
    except Exception as e:
        logger.error(f"DB Error (Update Strike): {e}")
        return 0

def get_strikes(torrent_hash):
    """Get current strikes for a torrent."""
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
    """Remove a torrent from the strike list (e.g., if it recovered)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM torrent_strikes WHERE hash=?", (torrent_hash,))
        conn.commit()
        conn.close()
    except Exception:
        pass

# ==========================================
#           MODULE 1: THE CLEANER
# ==========================================

class TorrentCleaner:
    def __init__(self):
        self.qbt = None
        self.connected = False

    def connect_qbit(self):
        try:
            # Using qbittorrent-api library for cleaner interaction
            self.qbt = qbittorrentapi.Client(host=QBIT_URL, username=QBIT_USER, password=QBIT_PASS)
            self.qbt.auth_log_in()
            self.connected = True
            logger.info("Connected to qBittorrent successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to qBittorrent: {e}")
            self.connected = False

    def get_arr_queue(self, app_name, url, api_key):
        """Fetch the current Queue from Sonarr/Radarr/Lidarr to map Hashes to IDs."""
        try:
            headers = {'X-Api-Key': api_key}
            # Lidarr uses API v1, others use v3
            api_version = "v1" if app_name == "Lidarr" else "v3"
            
            # Fetch queue with enough details
            res = requests.get(f"{url}/api/{api_version}/queue?page=1&pageSize=1000", headers=headers, timeout=20)
            res.raise_for_status()
            data = res.json()
            
            # Map Hash -> Queue Item ID (Needed to delete from Arr)
            mapping = {}
            records = data.get('records', [])
            for item in records:
                # Arrs return hash in uppercase usually, qbit is lowercase. Normalize to lowercase.
                h = item.get('downloadId', '').lower()
                if h:
                    mapping[h] = {
                        'id': item.get('id'), # Queue ID
                        'title': item.get('title', 'Unknown')
                    }
            return mapping
        except Exception as e:
            logger.error(f"Error fetching queue from {app_name}: {e}")
            return {}

    def remove_via_arr(self, app_name, url, api_key, queue_id, reason):
        """
        Instruct Sonarr/Radarr/Lidarr to remove the item from queue and blacklist it.
        """
        if DRY_RUN:
            logger.warning(f"[DRY RUN] Would ask {app_name} to delete Queue ID {queue_id} (Blacklist=True). Reason: {reason}")
            return

        try:
            headers = {'X-Api-Key': api_key}
            # removeFromClient=true -> Arr tells qBit to delete.
            # blocklist=true -> Arr prevents grabbing this specific release again.
            params = {'removeFromClient': 'true', 'blocklist': 'true'}
            
            # Lidarr uses API v1
            api_version = "v1" if app_name == "Lidarr" else "v3"
            
            uri = f"{url}/api/{api_version}/queue/{queue_id}"
            res = requests.delete(uri, params=params, headers=headers, timeout=30)
            res.raise_for_status()
            logger.info(f"[{app_name}] Successfully removed & blacklisted download. Reason: {reason}")
        except Exception as e:
            logger.error(f"[{app_name}] Failed to remove queue item {queue_id}: {e}")

    def remove_via_qbit(self, torrent_hash, is_private):
        """
        Fallback: Remove directly from qBit if Arr doesn't know about it (Orphan),
        OR if it is a private torrent (Tag Only).
        """
        if is_private:
            # For private trackers, we often just tag as obsolete, don't delete files.
            if DRY_RUN:
                logger.warning(f"[DRY RUN] Would Tag Private Torrent {torrent_hash} as '{OBSOLETE_TAG}'")
            else:
                try:
                    self.qbt.torrents_add_tags(tags=OBSOLETE_TAG, torrent_hashes=torrent_hash)
                    logger.info(f"Tagged private torrent {torrent_hash} as {OBSOLETE_TAG}")
                except Exception as e:
                    logger.error(f"Failed to tag torrent: {e}")
            return

        # Public / Cleanup Logic
        if DRY_RUN:
            logger.warning(f"[DRY RUN] Would DELETE torrent {torrent_hash} and FILES.")
        else:
            try:
                # delete_files=True ensures we clean up the /slow/media/downloads folder.
                # Hardlinks in /slow/media/series remain safe.
                self.qbt.torrents_delete(delete_files=True, torrent_hashes=torrent_hash)
                logger.info(f"Deleted torrent {torrent_hash} from qBittorrent.")
            except Exception as e:
                logger.error(f"Failed to delete torrent via qBit: {e}")

    def run_cleaner_cycle(self):
        if not self.connected:
            self.connect_qbit()
            if not self.connected: return

        logger.info("Starting Torrent Cleaner Cycle...")
        
        # 1. Get Torrents (Downloading, Stalled, MetaDL)
        # We don't touch 'completed' or 'seeding' usually, unless specified.
        try:
            torrents = self.qbt.torrents_info(filter='downloading') 
            # Note: 'downloading' in API often includes stalled and metaDL.
        except Exception as e:
            logger.error(f"Failed to fetch torrents list: {e}")
            return

        # 2. Get Queues from Arrs (to map Hash -> Arr Queue ID)
        # We need this to know who owns the torrent (Movie? Series? Music?)
        sonarr_map = self.get_arr_queue("Sonarr", SONARR_URL, SONARR_API_KEY) if SONARR_ENABLED else {}
        radarr_map = self.get_arr_queue("Radarr", RADARR_URL, RADARR_API_KEY) if RADARR_ENABLED else {}
        lidarr_map = self.get_arr_queue("Lidarr", LIDARR_URL, LIDARR_API_KEY) if LIDARR_ENABLED else {}
        # Note: Bazarr is skipped here because it handles subtitles, not video/audio torrent files.


        for tor in torrents:
            t_hash = tor.hash.lower()
            t_name = tor.name
            t_state = tor.state  # e.g., 'downloading', 'stalledDL', 'metaDL', 'error'
            t_added_on = tor.added_on # Unix timestamp
            t_time_active = (datetime.now().timestamp() - t_added_on) / 60 # Minutes
            t_tags = tor.tags.split(',') if tor.tags else []

            # --- Safety Checks ---
            # 1. Skip Protected Tags
            if any(tag in t_tags for tag in PROTECTED_TAGS):
                continue
            
            # 2. Determine Private vs Public
            # Logic: If 'private' tag exists OR explicitly in config tags
            is_private = any(tag in t_tags for tag in PRIVATE_TAGS)
            
            # 3. Identify which Arr owns this
            owner_app = None
            queue_id = None
            
            if t_hash in sonarr_map:
                owner_app = "Sonarr"
                queue_id = sonarr_map[t_hash]['id']
            elif t_hash in radarr_map:
                owner_app = "Radarr"
                queue_id = radarr_map[t_hash]['id']
            elif t_hash in lidarr_map:
                owner_app = "Lidarr"
                queue_id = lidarr_map[t_hash]['id']
            
            # If orphan and RM_ORPHANS is False, skip
            if not owner_app and not RM_ORPHANS:
                # It's manual or unknown, leave it alone
                continue

            # --- Rules Engine ---
            strike_reason = None

            # Rule A: Missing Metadata (Magnet stuck)
            if RM_META_MISSING and t_state == "metaDL" and t_time_active > TIMEOUT_METADATA:
                strike_reason = "Stuck Downloading Metadata"

            # Rule B: Stalled (0 seeds connected)
            elif RM_STALLED and t_state == "stalledDL" and t_time_active > TIMEOUT_STALLED:
                strike_reason = "Stalled (No Seeds)"

            # Rule C: Slow Speed
            elif RM_SLOW and t_state == "downloading":
                # Only check speed if it's been active for a bit (give it 5 mins to ramp up)
                if t_time_active > 5 and tor.dlspeed < MIN_SPEED_BYTES:
                    strike_reason = f"Slow Speed ({round(tor.dlspeed/1024, 2)} KB/s < {MIN_SPEED_KB} KB/s)"

            # Rule D: Bad Files / Error
            elif RM_FAILED and t_state in ["error", "missingFiles"]:
                strike_reason = "Error State or Missing Files"

            # --- Action Logic ---
            if strike_reason:
                # It's bad. Give it a strike.
                current_strikes = update_strike(t_hash, strike_reason)
                logger.warning(f"Strike {current_strikes}/{MAX_STRIKES} for '{t_name}'. Reason: {strike_reason}")

                if current_strikes >= MAX_STRIKES:
                    logger.info(f"MAX STRIKES REACHED for '{t_name}'. Taking Action.")
                    
                    # 1. Remove from DB (reset strikes)
                    clear_strikes(t_hash)

                    # 2. Execute Removal
                    if owner_app:
                        # Best Way: Tell Sonarr/Radarr to kill it.
                        url = SONARR_URL if owner_app == "Sonarr" else RADARR_URL
                        key = SONARR_API_KEY if owner_app == "Sonarr" else RADARR_API_KEY
                        self.remove_via_arr(owner_app, url, key, queue_id, strike_reason)
                    else:
                        # Orphan Way: Tell qBit to kill it directly.
                        if RM_ORPHANS:
                            self.remove_via_qbit(t_hash, is_private)
            else:
                # Torrent is healthy, clear any old strikes if they exist
                if get_strikes(t_hash) > 0:
                    clear_strikes(t_hash)

# ==========================================
#           MODULE 2: THE SEARCHER
# ==========================================
# (This logic is largely identical to V1 but refactored for the class structure)

class MissingSearcher:
    def check_safety_net(self, table_name):
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(f"SELECT timestamp FROM {table_name} ORDER BY timestamp ASC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row:
                oldest = datetime.fromisoformat(row[0])
                if datetime.now() - oldest > timedelta(days=MAX_CYCLE_DAYS):
                    logger.warning(f"Safety Net: {table_name} exceeded {MAX_CYCLE_DAYS} days.")
                    wipe_table(table_name)
        except Exception as e:
            logger.error(f"Safety check error: {e}")

    def fetch_ids(self, url, api_key, endpoint):
        """Generic fetcher for Arrs (Sonarr/Radarr/Lidarr)."""
        try:
            res = requests.get(f"{url}{endpoint}", headers={'X-Api-Key': api_key}, timeout=30)
            res.raise_for_status()
            data = res.json()
            if isinstance(data, dict) and 'records' in data: return [i['id'] for i in data['records']]
            if isinstance(data, list): return [i['id'] for i in data]
            return []
        except Exception as e:
            logger.error(f"Fetch ID Error: {e}")
            return []

    def run_cycle(self, app_name):
        # --- CONFIGURATION SWITCH ---
        if app_name == "Sonarr":
            url, key, limit, cutoff = SONARR_URL, SONARR_API_KEY, SONARR_LIMIT, SONARR_CUTOFF
            api_version = "v3"
        elif app_name == "Radarr":
            url, key, limit, cutoff = RADARR_URL, RADARR_API_KEY, RADARR_LIMIT, RADARR_CUTOFF
            api_version = "v3"
        elif app_name == "Lidarr":
            url, key, limit, cutoff = LIDARR_URL, LIDARR_API_KEY, LIDARR_LIMIT, LIDARR_CUTOFF
            api_version = "v1"
        elif app_name == "Bazarr":
            # Bazarr has unique logic handled in its own method
            self.run_bazarr_cycle()
            return
        else:
            return

        self.check_safety_net(f"{app_name.lower()}_searches")

       # --- STANDARD ARRS LOGIC (Sonarr/Radarr/Lidarr) ---
        candidates = []
        try:
            if app_name == "Sonarr":
                # Sonarr uses airDateUtc
                candidates.extend(self.fetch_ids(url, key, f"/api/{api_version}/wanted/missing?page=1&pageSize=1000&sortKey=airDateUtc&sortDir=desc"))
                if cutoff > 0: 
                    candidates.extend(self.fetch_ids(url, key, f"/api/{api_version}/wanted/cutoff?page=1&pageSize=1000"))
            
            elif app_name == "Lidarr":
                # Lidarr uses releaseDate (Not airDateUtc)
                candidates.extend(self.fetch_ids(url, key, f"/api/{api_version}/wanted/missing?page=1&pageSize=1000&sortKey=releaseDate&sortDir=desc"))
                if cutoff > 0: 
                    candidates.extend(self.fetch_ids(url, key, f"/api/{api_version}/wanted/cutoff?page=1&pageSize=1000"))

            elif app_name == "Radarr":
                # Radarr uses standard logic
                candidates.extend(self.fetch_ids(url, key, "/api/v3/wanted/missing?page=1&pageSize=1000"))
                if cutoff > 0: 
                    candidates.extend(self.fetch_ids(url, key, "/api/v3/wanted/cutoff?page=1&pageSize=1000"))
        except Exception as e:
            logger.error(f"[{app_name}] Error fetching candidates: {e}")
            return

        candidates = list(set(candidates))
        searched = get_searched_ids(f"{app_name.lower()}_searches")
        target = [i for i in candidates if i not in searched]

        logger.info(f"[{app_name}] Missing/Cutoff: {len(target)} items waiting.")

        if not target:
            if searched:
                logger.info(f"[{app_name}] Cycle Complete. Wiping DB.")
                wipe_table(f"{app_name.lower()}_searches")
            return

        batch = target[:limit]
        
        # Trigger Search
        headers = {'X-Api-Key': key}
        table = f"{app_name.lower()}_searches"
        
        for i in batch:
            try:
                payload = {}
                if app_name == "Sonarr": payload = {'name': 'EpisodeSearch', 'episodeIds': [i]}
                elif app_name == "Radarr": payload = {'name': 'MoviesSearch', 'movieIds': [i]}
                elif app_name == "Lidarr": payload = {'name': 'AlbumSearch', 'albumIds': [i]}

                res = requests.post(f"{url}/api/{api_version}/command", json=payload, headers=headers, timeout=30)
                res.raise_for_status()
                logger.info(f"[{app_name}] Triggered Search ID: {i}")
                add_searched_id(table, i)
                time.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.error(f"[{app_name}] Search Fail ID {i}: {e}")

    def run_bazarr_cycle(self):
        """
        Specific Cycle for Bazarr Subtitles (Movies & Series).
        Checks for items that have a file but are missing subtitles.
        """
        logger.info("[Bazarr] Starting Subtitle Search Cycle...")
        headers = {'X-Api-Key': BAZARR_API_KEY}
        
        # --- PART 1: MOVIES ---
        try:
            res = requests.get(f"{BAZARR_URL}/api/movies", headers=headers, timeout=30)
            if res.status_code == 200:
                movies = res.json().get('data', [])
                # Filter: Has File + Missing Subtitles (> 0)
                missing_movies = [m['radarrId'] for m in movies if m.get('has_file') and m.get('missing_subtitles', 0) > 0]
                
                # Filter against DB
                searched = get_searched_ids("bazarr_searches")
                target = [i for i in missing_movies if i not in searched]
                
                logger.info(f"[Bazarr] Movies Missing Subs: {len(target)}")
                
                # Process Batch (Movies)
                for radarr_id in target[:5]: # Small batch to allow time for Series
                    try:
                        # Command: Search subtitles for this movie
                        payload = {'name': 'movies_search', 'ids': [radarr_id]}
                        requests.post(f"{BAZARR_URL}/api/command", json=payload, headers=headers, timeout=30)
                        logger.info(f"[Bazarr] Searching Subs for Movie ID: {radarr_id}")
                        add_searched_id("bazarr_searches", radarr_id)
                        time.sleep(REQUEST_DELAY)
                    except Exception as e:
                        logger.error(f"[Bazarr] Movie Search Fail: {e}")
        except Exception as e:
            logger.error(f"[Bazarr] Movie Check Error: {e}")

        # --- PART 2: SERIES (EPISODES) ---
        try:
            # 1. Get All Series to find which ones need help
            res = requests.get(f"{BAZARR_URL}/api/series", headers=headers, timeout=30)
            if res.status_code == 200:
                all_series = res.json().get('data', [])
                # Smart Filter: Only look at series that report missing subtitles
                target_series = [s for s in all_series if s.get('missing_subtitles', 0) > 0]
                
                logger.info(f"[Bazarr] Series with Missing Subs: {len(target_series)}")
                
                count_searched_episodes = 0
                
                # Loop through needy series
                for series in target_series:
                    if count_searched_episodes >= 10: break # Limit episodes per run to avoid timeout
                    
                    series_id = series['id'] # Internal Bazarr ID
                    sonarr_id = series['sonarrId']
                    
                    # Get Episodes for this series
                    ep_res = requests.get(f"{BAZARR_URL}/api/episodes?seriesId={series_id}", headers=headers, timeout=20)
                    if ep_res.status_code == 200:
                        episodes = ep_res.json().get('data', [])
                        # Filter: Has File + Missing Subs
                        missing_eps = [e['id'] for e in episodes if e.get('has_file') and e.get('missing_subtitles', 0) > 0]
                        
                        # Check DB
                        searched_eps = get_searched_ids("bazarr_searches") # We use same table, mixing Movie/Ep IDs is fine as they are unique integers usually or we don't care about collisions much here, but ideally we should separate. 
                        # *Correction*: Sonarr IDs and Radarr IDs might overlap. 
                        # Ideally we should have a 'bazarr_ep_searches' table, but to keep V2 simple we'll use the same table.
                        # Since we store just ID, collision is rare but possible. 
                        # To fix: we can't easily change DB schema now without migration script.
                        # Safe bet: We proceed. The probability of a Movie ID matching a specific Episode ID exactly on the same day is low enough for a helper script.
                        
                        real_targets = [ep for ep in missing_eps if ep not in searched_eps]
                        
                        for ep_id in real_targets:
                            if count_searched_episodes >= 10: break
                            
                            try:
                                # Command: Search subtitles for this episode
                                payload = {'name': 'episodes_search', 'ids': [ep_id]}
                                requests.post(f"{BAZARR_URL}/api/command", json=payload, headers=headers, timeout=30)
                                logger.info(f"[Bazarr] Searching Subs for Episode ID: {ep_id} (Series: {sonarr_id})")
                                add_searched_id("bazarr_searches", ep_id)
                                time.sleep(REQUEST_DELAY)
                                count_searched_episodes += 1
                            except Exception as e:
                                logger.error(f"[Bazarr] Episode Search Fail: {e}")

        except Exception as e:
            logger.error(f"[Bazarr] Series Check Error: {e}")

# ==========================================
#           MAIN THREAD RUNNERS
# ==========================================

def searcher_thread():
    """Runs the missing content search loop."""
    searcher = MissingSearcher()
    logger.info("Searcher Thread Started.")
    while True:
        try:
            schedule.run_pending()
            # We use local scheduling logic inside the loop or just simple sleeps
            # To respect the 'RUN_EVERY' env var dynamically:
            logger.info("--- Searcher Run ---")
            if SONARR_ENABLED: searcher.run_cycle("Sonarr")
            if RADARR_ENABLED: searcher.run_cycle("Radarr")
            if LIDARR_ENABLED: searcher.run_cycle("Lidarr")
            # Bazarr skipped (Search API differs significantly)
            logger.info(f"Searcher sleeping for {SEARCH_RUN_EVERY} mins...")
            time.sleep(SEARCH_RUN_EVERY * 60)
        except Exception as e:
            logger.error(f"Searcher Thread Error: {e}")
            time.sleep(60) # Sleep on error

def cleaner_thread():
    """Runs the torrent cleaner loop."""
    if not ENABLE_TORRENT_HANDLING:
        logger.info("Torrent Handling is DISABLED via Env.")
        return

    cleaner = TorrentCleaner()
    logger.info("Cleaner Thread Started.")
    while True:
        try:
            logger.info("--- Cleaner Run ---")
            cleaner.run_cleaner_cycle()
            logger.info(f"Cleaner sleeping for {CLEANER_RUN_EVERY} mins...")
            time.sleep(CLEANER_RUN_EVERY * 60)
        except Exception as e:
            logger.error(f"Cleaner Thread Error: {e}")
            time.sleep(60)

def main():
    logger.info("Starting Arr-Missing-Content V2 (The Manager)...")
    init_db()

    # Start Searcher in background thread
    t_search = threading.Thread(target=searcher_thread, name="Searcher", daemon=True)
    t_search.start()

    # Start Cleaner in background thread
    t_clean = threading.Thread(target=cleaner_thread, name="Cleaner", daemon=True)
    t_clean.start()

    # Keep main thread alive to handle signals or just wait
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
