# """
# ==============================================================================
# FILE: cleaner.py
# ROLE: The Executioner
# DESCRIPTION:
# Connects directly to qBittorrent. Evaluates download health, speeds, and 
# statuses. If a torrent is stalled, missing metadata, or too slow, it issues 
# strikes. If max strikes are reached, it deletes the torrent and blacklists 
# it in the Arr apps.
# ==============================================================================
# """

import requests
import qbittorrentapi
import logging
from datetime import datetime

# Import the dynamic config manager
from config import cfg

# Import specific database functions to track torrent strikes
from database import update_strike, clear_strikes, get_strikes

# Initialize the logger for this specific module
logger = logging.getLogger(__name__)

# ==============================================================================
# MODULE 1: THE CLEANER
# ==============================================================================
class TorrentCleaner:
    """Checks qBittorrent and deletes bad, stalled, or slow torrents."""
    def __init__(self):
        self.qbt = None
        self.connected = False

    def connect_qbit(self):
        """Connects to qBittorrent using details from config."""
        try:
            self.qbt = qbittorrentapi.Client(host=cfg.QBIT_URL, username=cfg.QBIT_USER, password=cfg.QBIT_PASS)
            self.qbt.auth_log_in()
            self.connected = True
        except Exception as e:
            logger.error(f"Failed to connect to qBittorrent: {e}")
            self.connected = False

    def get_arr_queue(self, app_name, url, api_key):
        """Downloads the current queue from Sonarr/Radarr/Lidarr."""
        try:
            headers = {'X-Api-Key': api_key}
            api_version = "v1" if app_name == "Lidarr" else "v3"
            res = requests.get(f"{url}/api/{api_version}/queue?page=1&pageSize=1000", headers=headers, timeout=20)
            res.raise_for_status()
            data = res.json()
            mapping = {}
            for item in data.get('records', []):
                h = item.get('downloadId', '').lower()
                if h:
                    mapping[h] = {'id': item.get('id'), 'title': item.get('title', 'Unknown')}
            return mapping
        except Exception:
            return {}

    def remove_via_arr(self, app_name, url, api_key, queue_id, reason):
        """Tells the Arr app to delete the torrent and add it to the blocklist."""
        if cfg.DRY_RUN:
            logger.warning(f"[DRY RUN] Would tell {app_name} to delete Queue ID {queue_id}. Reason: {reason}")
            return
        try:
            headers = {'X-Api-Key': api_key}
            params = {'removeFromClient': 'true', 'blocklist': 'true'}
            api_version = "v1" if app_name == "Lidarr" else "v3"
            requests.delete(f"{url}/api/{api_version}/queue/{queue_id}", params=params, headers=headers, timeout=30)
            logger.info(f"[{app_name}] Successfully deleted & blacklisted. Reason: {reason}")
        except Exception as e:
            logger.error(f"[{app_name}] Failed to delete queue item: {e}")

    def remove_via_qbit(self, torrent_hash, is_private):
        """Directly deletes an orphan torrent from qBittorrent."""
        if is_private:
            if cfg.DRY_RUN:
                logger.warning(f"[DRY RUN] Would add tag '{cfg.OBSOLETE_TAG}' to Private Torrent {torrent_hash}")
            else:
                try:
                    self.qbt.torrents_add_tags(tags=cfg.OBSOLETE_TAG, torrent_hashes=torrent_hash)
                    logger.info(f"Tagged private torrent {torrent_hash} as {cfg.OBSOLETE_TAG}")
                except Exception:
                    pass
            return

        if cfg.DRY_RUN:
            logger.warning(f"[DRY RUN] Would DELETE orphan torrent {torrent_hash} AND its files.")
        else:
            try:
                self.qbt.torrents_delete(delete_files=True, torrent_hashes=torrent_hash)
                logger.info(f"Deleted orphan torrent {torrent_hash} from qBittorrent.")
            except Exception:
                pass

    def run_cleaner_cycle(self):
        """Main loop that evaluates torrent health and gives strikes."""
        if not self.connected:
            self.connect_qbit()
            if not self.connected: return

        logger.info("Starting Torrent Cleaner Cycle...")
        try:
            # We only care about torrents that are currently downloading
            torrents = self.qbt.torrents_info(filter='downloading') 
        except Exception:
            return

        sonarr_map = self.get_arr_queue("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY) if cfg.SONARR_ENABLED else {}
        radarr_map = self.get_arr_queue("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY) if cfg.RADARR_ENABLED else {}
        lidarr_map = self.get_arr_queue("Lidarr", cfg.LIDARR_URL, cfg.LIDARR_API_KEY) if cfg.LIDARR_ENABLED else {}

        for tor in torrents:
            t_hash = tor.hash.lower()
            t_name = tor.name
            t_state = tor.state
            t_added_on = tor.added_on
            t_time_active = (datetime.now().timestamp() - t_added_on) / 60
            t_tags = tor.tags.split(',') if tor.tags else []

            # Ignore protected torrents entirely
            if any(tag in t_tags for tag in cfg.PROTECTED_TAGS): continue
            
            # Check if this torrent is from a private tracker
            is_private = any(tag in t_tags for tag in cfg.PRIVATE_TAGS)
            
            # Find which app requested this torrent
            owner_app = None
            queue_id = None
            if t_hash in sonarr_map:
                owner_app, queue_id = "Sonarr", sonarr_map[t_hash]['id']
            elif t_hash in radarr_map:
                owner_app, queue_id = "Radarr", radarr_map[t_hash]['id']
            elif t_hash in lidarr_map:
                owner_app, queue_id = "Lidarr", lidarr_map[t_hash]['id']
            
            # If no app owns it, and we don't clean orphans, skip it
            if not owner_app and not cfg.RM_ORPHANS: continue

            # Determine if it deserves a strike
            strike_reason = None
            if cfg.RM_META_MISSING and t_state == "metaDL" and t_time_active > cfg.TIMEOUT_METADATA:
                strike_reason = "Stuck Downloading Metadata"
            elif cfg.RM_STALLED and t_state == "stalledDL" and t_time_active > cfg.TIMEOUT_STALLED:
                strike_reason = "Stalled (No Seeds)"
            elif cfg.RM_SLOW and t_state == "downloading" and t_time_active > 5 and tor.dlspeed < cfg.MIN_SPEED_BYTES:
                strike_reason = "Downloading too slowly"
            elif cfg.RM_FAILED and t_state in ["error", "missingFiles"]:
                strike_reason = "Critical Error State"

            # Apply strike logic
            if strike_reason:
                current_strikes = update_strike(t_hash, strike_reason)
                logger.warning(f"Strike {current_strikes}/{cfg.MAX_STRIKES} for '{t_name}'. Reason: {strike_reason}")
                if current_strikes >= cfg.MAX_STRIKES:
                    clear_strikes(t_hash) # Reset memory before deletion
                    if owner_app:
                        url = cfg.SONARR_URL if owner_app == "Sonarr" else cfg.RADARR_URL
                        key = cfg.SONARR_API_KEY if owner_app == "Sonarr" else cfg.RADARR_API_KEY
                        self.remove_via_arr(owner_app, url, key, queue_id, strike_reason)
                    else:
                        if cfg.RM_ORPHANS: self.remove_via_qbit(t_hash, is_private)
            else:
                # If torrent becomes healthy again, clear its strikes
                if get_strikes(t_hash) > 0: clear_strikes(t_hash)