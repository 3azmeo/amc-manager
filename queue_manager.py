# """
# ==============================================================================
# FILE: queue_manager.py
# ROLE: Smart Batch & Cross-Arr Routing (V3.6)
# DESCRIPTION:
# Monitors the Arr queues for stuck items.
# - Smart Batch: Forces a deep scan for folders stuck in Sonarr/Radarr.
# - Cross-Routing: If an item is totally unrecognized, it uses HARDLINKS to safely 
#   duplicate the stuck folder into the manual-import staging area. This protects 
#   the original files so your torrent client can continue seeding.
# ==============================================================================
# """

import os
import time
import shutil
import requests
import logging

from config import cfg

logger = logging.getLogger(__name__)

class QueueManager:
    """Handles stuck queue items, forced imports, and cross-application routing."""
    
    def get_queue(self, app_name, url, api_key):
        """Fetches the current active queue from the Arr application."""
        try:
            res = requests.get(f"{url}/api/v3/queue?page=1&pageSize=100", headers={'X-Api-Key': api_key}, timeout=15)
            if res.status_code == 200:
                return res.json().get('records', [])
        except Exception as e:
            logger.error(f"[{app_name}] Failed to get queue: {e}")
        return []

    def trigger_scan(self, app_name, url, api_key, path):
        """Tells the Arr application to force a scan on a specific path."""
        try:
            payload = {"name": "DownloadedEpisodesScan", "path": path} if app_name == "Sonarr" else {"name": "DownloadedMoviesScan", "path": path}
            res = requests.post(f"{url}/api/v3/command", json=payload, headers={'X-Api-Key': api_key}, timeout=15)
            return res.status_code in [200, 201]
        except Exception as e:
            logger.error(f"[{app_name}] Failed to trigger scan: {e}")
            return False

    def remove_from_queue(self, app_name, url, api_key, item_id):
        """Removes a stuck item from the Arr queue without deleting the files."""
        try:
            res = requests.delete(f"{url}/api/v3/queue/{item_id}?removeFromClient=false&blocklist=false", headers={'X-Api-Key': api_key}, timeout=15)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"[{app_name}] Failed to remove queue item: {e}")
            return False

    def hardlink_or_copy(self, src, dst):
        """
        Recursively hardlinks files from src to dst. 
        Falls back to regular copy if hardlinks are not supported across drives.
        """
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            for item in os.listdir(src):
                self.hardlink_or_copy(os.path.join(src, item), os.path.join(dst, item))
        else:
            try:
                os.link(src, dst)
            except OSError:
                # If hardlink fails (e.g., crossing filesystems), fallback to a standard copy
                shutil.copy2(src, dst)

    def route_to_manual_import(self, source_path, title):
        """
        Cross-Routing Magic: Hardlinks the stuck folder to our manual-import staging area.
        Our importer.py will then pick it up, score it, auto-add it, and link it to the Arr app!
        """
        if not os.path.exists(source_path):
            return False
            
        import_path = cfg.MANUAL_IMPORT_PATH
        # Ensure the manual import directory exists (so the user doesn't have to create it)
        os.makedirs(import_path, exist_ok=True)
        
        target_path = os.path.join(import_path, os.path.basename(source_path))
        
        try:
            if cfg.DRY_RUN:
                logger.info(f"[AdvancedQueue] [DRY RUN] Would HARDLINK '{title}' to {import_path}")
            else:
                self.hardlink_or_copy(source_path, target_path)
                logger.info(f"[AdvancedQueue] CROSS-ROUTED: Hardlinked '{title}' to {import_path} for smart evaluation.")
            return True
        except Exception as e:
            logger.error(f"[AdvancedQueue] Failed to cross-route '{title}': {e}")
            return False

    def process_app_queue(self, app_name, url, api_key):
        """Analyzes the queue and makes decisions on stuck items."""
        queue_items = self.get_queue(app_name, url, api_key)
        
        for item in queue_items:
            # We only care about items that are fully downloaded but have a warning/error (stuck)
            status = item.get('status')
            state = item.get('trackedDownloadState')
            
            if status == 'completed' and state in ['warning', 'error']:
                title = item.get('title', 'Unknown Title')
                path = item.get('outputPath')
                item_id = item.get('id')
                series_or_movie_id = item.get('seriesId') or item.get('movieId')
                
                if not path or not os.path.exists(path):
                    continue
                    
                messages = [msg.get('title', '') for msg in item.get('statusMessages', [])]
                error_reasons = " | ".join(messages).lower()

                # --- SMART BATCH LOGIC ---
                if cfg.ENABLE_SMART_BATCH and series_or_movie_id:
                    if cfg.DRY_RUN:
                        logger.info(f"[AdvancedQueue] [DRY RUN] Would force deep scan on {app_name} batch: {title}")
                    else:
                        logger.info(f"[AdvancedQueue] Forcing deep scan for stuck {app_name} batch: {title}")
                        self.trigger_scan(app_name, url, api_key, path)
                
                # --- CROSS-ARR ROUTING LOGIC ---
                elif cfg.ENABLE_CROSS_ARR and not series_or_movie_id and "unknown" in error_reasons:
                    if cfg.DRY_RUN:
                        logger.info(f"[AdvancedQueue] [DRY RUN] '{title}' is unrecognized by {app_name}. Would route to manual-import.")
                    else:
                        logger.info(f"[AdvancedQueue] '{title}' is unrecognized by {app_name}. Hardlinking to manual-import...")
                        success = self.route_to_manual_import(path, title)
                        if success:
                            self.remove_from_queue(app_name, url, api_key, item_id)

    def run_cycle(self):
        """Main execution loop for the Queue Manager."""
        if not cfg.ENABLE_SMART_BATCH and not cfg.ENABLE_CROSS_ARR:
            return
            
        logger.info("Starting Advanced Queue Manager Cycle...")
        
        if cfg.SONARR_ENABLED:
            self.process_app_queue("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY)
            
        if cfg.RADARR_ENABLED:
            self.process_app_queue("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY)