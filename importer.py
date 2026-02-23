"""
==============================================================================
FILE: importer.py
ROLE: Smart Auto-Importer (v3.3)
DESCRIPTION:
Monitors a specific directory for manual uploads. Checks with Arr APIs to 
score and validate the items. Features detailed logging at every single step.
==============================================================================
"""

import os
import time
import shutil
import requests
import logging
import re

from config import cfg
from queue_manager import QueueManager

logger = logging.getLogger(__name__)

class ManualImporter:
    """Evaluates, imports, and organizes manually downloaded files."""
    
    def __init__(self):
        self.success_dir = os.path.join(cfg.MANUAL_IMPORT_PATH, "success")
        self.failed_dir = os.path.join(cfg.MANUAL_IMPORT_PATH, "failed")

    def ensure_directories(self):
        """Creates the necessary import, success, and failed directories."""
        os.makedirs(cfg.MANUAL_IMPORT_PATH, exist_ok=True)
        os.makedirs(self.success_dir, exist_ok=True)
        os.makedirs(self.failed_dir, exist_ok=True)

    def move_file(self, file_path, target_dir):
        """Helper function to safely move a file/folder to a new directory."""
        if cfg.DRY_RUN:
            logger.info(f"[DRY RUN] Would move '{os.path.basename(file_path)}' to {os.path.basename(target_dir)}/")
            return
        try:
            target_path = os.path.join(target_dir, os.path.basename(file_path))
            shutil.move(file_path, target_path)
            logger.info(f"[Manual Import] Moved '{os.path.basename(file_path)}' to {os.path.basename(target_dir)}/")
        except Exception as e:
            logger.error(f"[Manual Import] Failed to move '{file_path}': {e}")

    def evaluate_api(self, app_name, url, api_key):
        """
        Phase 2: Identification & Scoring.
        Asks the Arr API to evaluate all files/folders in the import folder.
        """
        accepted = []
        rejected = []
        
        logger.info(f"[{app_name}] Sending request to evaluate folder: {cfg.MANUAL_IMPORT_PATH}")
        
        try:
            api_version = "v1" if app_name == "Lidarr" else "v3"
            res = requests.get(f"{url}/api/{api_version}/manualimport?folder={cfg.MANUAL_IMPORT_PATH}", headers={'X-Api-Key': api_key}, timeout=30)
            
            if res.status_code != 200:
                logger.error(f"[{app_name}] Evaluation API failed with code {res.status_code}. Details: {res.text}")
                return [], []
            
            data = res.json()
            logger.info(f"[{app_name}] API scanned the folder and returned {len(data)} items to process.")
            
            for item in data:
                path = item.get('path', 'Unknown')
                
                # Ignore items that are already inside our success/failed folders
                if self.success_dir in path or self.failed_dir in path:
                    continue
                
                rejections = item.get('rejections', [])
                if rejections:
                    reason = rejections[0].get('reason', 'Unknown Reason')
                    logger.warning(f"[{app_name}] REJECTED by API: '{os.path.basename(path)}' - Reason: {reason}")
                    rejected.append((path, reason))
                else:
                    logger.info(f"[{app_name}] ACCEPTED by API: '{os.path.basename(path)}'")
                    accepted.append(path)
                    
            return accepted, rejected
        except Exception as e:
            logger.error(f"[{app_name}] API Connection error during evaluation: {e}")
            return [], []
    
    def clean_title_for_search(self, raw_name):
        """
        Phase 3.5a: Cleans the filename so the Arr API can understand it.
        Removes release groups like [Judas], tags inside (), and extensions.
        """
        # Remove the file extension (e.g., .mkv, .mp4)
        name = os.path.splitext(raw_name)[0]
        
        # Remove anything inside square brackets [] (Usually Release Groups)
        name = re.sub(r'\[.*?\]', '', name)
        
        # Remove anything inside parentheses () (Usually year or extra tags)
        name = re.sub(r'\(.*?\)', '', name)
        
        # Replace dots and underscores with spaces for a cleaner search query
        name = name.replace('.', ' ').replace('_', ' ')
        
        # Return the cleaned string without extra leading/trailing spaces
        return name.strip()

    def lookup_missing_media(self, app_name, url, api_key, file_path):
        """
        Phase 3.5b: Looks up the rejected file in TVDB/TMDB.
        Now it tries the raw name first, and if that fails, it tries the cleaned name.
        """
        raw_name = os.path.basename(file_path)
        clean_name = self.clean_title_for_search(raw_name)
        
        logger.info(f"[{app_name}] Auto-Add Lookup: Asking API to identify '{raw_name}'...")
        
        endpoint = "/api/v3/series/lookup" if app_name == "Sonarr" else "/api/v3/movie/lookup"
        
        # Define a helper function to avoid repeating the API call code
        def fetch_api(search_term):
            try:
                res = requests.get(f"{url}{endpoint}?term={search_term}", headers={'X-Api-Key': api_key}, timeout=30)
                if res.status_code == 200 and res.json():
                    return res.json()[0] # Return the best match
            except Exception as e:
                logger.error(f"[{app_name}] Lookup error for '{search_term}': {e}")
            return None

        # Attempt 1: Try with the original name (minus extension)
        best_match = fetch_api(os.path.splitext(raw_name)[0])
        
        # Attempt 2: If attempt 1 fails, try with the heavily cleaned name
        if not best_match and clean_name:
            logger.info(f"[{app_name}] Raw name failed. Retrying with clean name: '{clean_name}'...")
            best_match = fetch_api(clean_name)
            
            # Attempt 3: If it's a Radarr "Movie" and still failing, strip the word "Movie" and numbers
            if not best_match and app_name == "Radarr" and "movie" in clean_name.lower():
                ultra_clean = re.sub(r'(?i)movie\s*\d*', '', clean_name).strip()
                logger.info(f"[{app_name}] Retrying by stripping 'Movie' tags: '{ultra_clean}'...")
                best_match = fetch_api(ultra_clean)

        # Process the final result
        if best_match:
            title = best_match.get('title', 'Unknown Title')
            year = best_match.get('year', 'Unknown Year')
            media_id = best_match.get('tvdbId') or best_match.get('tmdbId') or 'Unknown ID'
            logger.info(f"[{app_name}] Auto-Add Lookup SUCCESS: Found '{title} ({year})' [ID: {media_id}]!")
            return best_match
        else:
            logger.warning(f"[{app_name}] Auto-Add Lookup: Exhausted all search methods. Could not find a match for '{raw_name}'.")
            return None

    def get_profile_id(self, app_name, url, api_key, profile_name):
        """
        Phase 3.6: Translates the string profile name (e.g., 'best') into an ID integer.
        Fetches the active profiles from the Arr app and matches the name.
        """
        try:
            res = requests.get(f"{url}/api/v3/qualityprofile", headers={'X-Api-Key': api_key}, timeout=15)
            if res.status_code == 200:
                profiles = res.json()
                for p in profiles:
                    # Match the name without being case-sensitive
                    if p.get('name', '').lower() == profile_name.lower():
                        return p.get('id')
                
                # If the user typed a name that doesn't exist, use the first one as fallback
                if profiles:
                    fallback_id = profiles[0].get('id')
                    logger.warning(f"[{app_name}] Profile '{profile_name}' not found. Falling back to ID: {fallback_id}")
                    return fallback_id
            return 1 # Ultimate fallback ID
        except Exception as e:
            logger.error(f"[{app_name}] Failed to fetch quality profiles: {e}")
            return 1

    def add_media(self, app_name, url, api_key, media_data, root_folder, profile_id):
        """
        Phase 3.7: Sends the actual POST request to add the missing Series/Movie.
        """
        title = media_data.get('title', 'Unknown')
        
        if cfg.DRY_RUN:
            logger.info(f"[DRY RUN] Would ADD '{title}' to {app_name} at '{root_folder}' with Profile ID {profile_id}")
            return True # Pretend it succeeded so it doesn't move the file to failed/
            
        try:
            headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}
            if app_name == "Sonarr":
                payload = {
                    "title": title,
                    "tvdbId": media_data.get('tvdbId'),
                    "qualityProfileId": profile_id,
                    "languageProfileId": 1, # 1 is usually 'Any' or English
                    "rootFolderPath": root_folder,
                    "monitored": True,
                    "seriesType": "anime" if "anime" in root_folder.lower() else "standard",
                    "addOptions": {"searchForMissingEpisodes": False} # The Hunter thread will handle searching later
                }
                endpoint = "/api/v3/series"
            else:
                payload = {
                    "title": title,
                    "tmdbId": media_data.get('tmdbId'),
                    "qualityProfileId": profile_id,
                    "rootFolderPath": root_folder,
                    "monitored": True,
                    "addOptions": {"searchForMovie": False}
                }
                endpoint = "/api/v3/movie"
                
            res = requests.post(f"{url}{endpoint}", json=payload, headers=headers, timeout=30)
            
            # API returns 201 (Created) or 200 (OK) on success
            if res.status_code in [200, 201]:
                logger.info(f"[{app_name}] SUCCESS: Auto-Added '{title}' to the database!")
                return True
            else:
                logger.error(f"[{app_name}] Failed to add '{title}'. Code: {res.status_code}. Response: {res.text}")
                return False
        except Exception as e:
            logger.error(f"[{app_name}] API error while adding media: {e}")
            return False

    def process_hardlinks_to_success(self):
        """
        Phase 4a: The Hardlink Detector.
        Checks if a file was successfully hardlinked by Sonarr/Radarr (st_nlink >= 2).
        """
        for filename in os.listdir(cfg.MANUAL_IMPORT_PATH):
            if filename in ['success', 'failed']:
                continue
                
            filepath = os.path.join(cfg.MANUAL_IMPORT_PATH, filename)
            
            # We only check hardlinks on actual files, not directories
            if os.path.isfile(filepath):
                try:
                    if os.stat(filepath).st_nlink >= 2:
                        if cfg.DRY_RUN:
                            logger.info(f"[DRY RUN] Would move successfully hardlinked file '{filename}' to success/")
                        else:
                            logger.info(f"[Manual Import] SUCCESS: Arr app hardlinked '{filename}'!")
                            self.move_file(filepath, self.success_dir)
                except Exception:
                    pass

    def cleanup_old_files(self, target_dir):
        """Phase 4b: Deletes files in success/failed folders if they are too old."""
        retention_mins = cfg.FAILED_RETENTION_MINS
        if not retention_mins or not os.path.exists(target_dir):
            return 
            
        now = time.time()
        retention_seconds = retention_mins * 60
        
        for filename in os.listdir(target_dir):
            filepath = os.path.join(target_dir, filename)
            if os.path.isfile(filepath):
                file_age = now - os.path.getmtime(filepath)
                if file_age > retention_seconds:
                    if cfg.DRY_RUN:
                        logger.warning(f"[DRY RUN] Would DELETE old file '{filename}' from {os.path.basename(target_dir)}/")
                    else:
                        try:
                            os.remove(filepath)
                            logger.info(f"[Cleanup] Deleted old file '{filename}' from {os.path.basename(target_dir)}/")
                        except Exception as e:
                            logger.error(f"[Cleanup] Failed to delete file '{filename}': {e}")

    def run_cycle(self):
        """Main execution loop for the Smart Manual Importer."""
        if not cfg.ENABLE_MANUAL_IMPORT:
            return
            
        self.ensure_directories()
        self.process_hardlinks_to_success()
        
        # Count items that are NOT the success/failed folders
        items = [f for f in os.listdir(cfg.MANUAL_IMPORT_PATH) if f not in ['success', 'failed']]
        
        if items:
            logger.info(f"[Manual Import] Found {len(items)} items/folders. Starting API Evaluation Phase...")
            
            s_acc, s_rej = self.evaluate_api("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY) if cfg.SONARR_ENABLED else ([], [])
            r_acc, r_rej = self.evaluate_api("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY) if cfg.RADARR_ENABLED else ([], [])
            
            logger.info(f"[Manual Import] SUMMARY - Sonarr (Accepted: {len(s_acc)}, Rejected: {len(s_rej)})")
            logger.info(f"[Manual Import] SUMMARY - Radarr (Accepted: {len(r_acc)}, Rejected: {len(r_rej)})")
            
            if not s_acc and not r_acc and not s_rej and not r_rej:
                logger.warning("[Manual Import] Arrs found nothing to process inside the folders! (Check formats or hidden files).")

            all_accepted = set(s_acc + r_acc)
            
            # Keeps track of what we added this cycle so we don't spam the API for episodes of the same show
            recently_added = set()
            
            # 3. Decision Engine: Process Rejections & Auto-Add Logic
            for path, reason in (s_rej + r_rej):
                if path not in all_accepted and os.path.exists(path):
                    
                    added_successfully = False
                    
                    # --- AUTO-ADD LOGIC ---
                    if "Unknown" in reason and cfg.ENABLE_AUTO_ADD:
                        app_n = "Sonarr" if "Series" in reason else "Radarr"
                        url_app = cfg.SONARR_URL if app_n == "Sonarr" else cfg.RADARR_URL
                        key_app = cfg.SONARR_API_KEY if app_n == "Sonarr" else cfg.RADARR_API_KEY
                        
                        if (app_n == "Sonarr" and cfg.SONARR_ENABLED) or (app_n == "Radarr" and cfg.RADARR_ENABLED):
                            match = self.lookup_missing_media(app_n, url_app, key_app, path)
                            
                            if match:
                                media_id = match.get('tvdbId') or match.get('tmdbId')
                                
                                if media_id not in recently_added:
                                    # Guess if it is anime based on genres from the Arr app or the file path
                                    is_anime = "Anime" in match.get('genres', []) or "anime" in path.lower()
                                    
                                    # Fetch the correct profile name and folder path from our dynamic config
                                    if app_n == "Sonarr":
                                        p_name = cfg.AUTO_ADD_SONARR_ANIME_PROFILE if is_anime else cfg.AUTO_ADD_SONARR_STD_PROFILE
                                        r_folder = cfg.AUTO_ADD_SONARR_ANIME_PATH if is_anime else cfg.AUTO_ADD_SONARR_STD_PATH
                                    else:
                                        p_name = cfg.AUTO_ADD_RADARR_ANIME_PROFILE if is_anime else cfg.AUTO_ADD_RADARR_STD_PROFILE
                                        r_folder = cfg.AUTO_ADD_RADARR_ANIME_PATH if is_anime else cfg.AUTO_ADD_RADARR_STD_PATH
                                        
                                    prof_id = self.get_profile_id(app_n, url_app, key_app, p_name)
                                    success = self.add_media(app_n, url_app, key_app, match, r_folder, prof_id)
                                    
                                    if success:
                                        recently_added.add(media_id)
                                        added_successfully = True
                                elif media_id in recently_added:
                                    # Already added this show in the current loop (e.g., episode 2 of the same show)
                                    added_successfully = True

                    # -------------------------------
                    
                    # If we failed to add it (or auto-add is off), move it to failed folder
                    if not added_successfully:
                        logger.warning(f"[Manual Import] FINAL REJECTION: '{os.path.basename(path)}' - Reason: {reason}")
                        self.move_file(path, self.failed_dir)
                    else:
                        # If added successfully, leave the file exactly where it is! 
                        # The next scan cycle will pick it up because Sonarr now knows the show.
                        logger.info(f"[Manual Import] Leaving '{os.path.basename(path)}' in staging folder for the next cycle.")

            queue_manager = QueueManager()
            if s_acc:
                # Tell Sonarr to scan the specific accepted folders
                queue_manager.trigger_scan("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY, cfg.MANUAL_IMPORT_PATH)
            if r_acc:
                queue_manager.trigger_scan("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY, cfg.MANUAL_IMPORT_PATH)

        self.cleanup_old_files(self.success_dir)
        self.cleanup_old_files(self.failed_dir)