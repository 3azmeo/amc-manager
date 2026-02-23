"""
==============================================================================
FILE: sync_mgr.py
ROLE: Profile & Format Sync Manager
DESCRIPTION:
1. Copies default templates to /config/defaults if they do not exist.
2. Downloads daily updates from TRaSH Guides to the trashguide-cache folder.
3. SMART PUSH: Fetches existing Custom Formats from Sonarr/Radarr. If a format 
   already exists, it safely updates it (PUT) to apply new regex logic without 
   destroying your quality profile scores. If it doesn't exist, it adds it (POST).
==============================================================================
"""

import os
import json
import shutil
import requests
import logging

from config import cfg

logger = logging.getLogger(__name__)

class ProfileSyncManager:
    """Manages the synchronization of local profiles and online guides updates."""
    
    def __init__(self):
        self.template_dir = "/app/defaults_template"
        self.live_dir = "/config/defaults"
        self.trash_cache_dir = os.path.join(self.live_dir, "trashguide-cache")
        
        self.endpoints = {
            "Sonarr_CF": ("https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/sonarr/cf", os.path.join(self.trash_cache_dir, "sonarr/cf")),
            "Sonarr_Profile": ("https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/sonarr/quality-profiles", os.path.join(self.trash_cache_dir, "sonarr/score")),
            "Radarr_CF": ("https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/radarr/cf", os.path.join(self.trash_cache_dir, "radarr/cf")),
            "Radarr_Profile": ("https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/radarr/quality-profiles", os.path.join(self.trash_cache_dir, "radarr/score"))
        }

    def setup_directories(self):
        """Copies the baked-in defaults_template to the user's /config volume."""
        if not os.path.exists(self.live_dir):
            logger.info("[Sync] User 'defaults' folder not found. Copying template from image...")
            try:
                if os.path.exists(self.template_dir):
                    shutil.copytree(self.template_dir, self.live_dir)
                    logger.info("[Sync] SUCCESS: Default files copied to /config/defaults!")
                else:
                    logger.error("[Sync] ERROR: Template directory missing from Docker image!")
            except Exception as e:
                logger.error(f"[Sync] Failed to copy defaults: {e}")

    def update_trash_guide_cache(self):
        """Downloads the latest Custom Formats and Profiles from GitHub."""
        if cfg.DRY_RUN:
            logger.info("[DRY RUN] Would connect to GitHub and download Guide updates.")
            return True

        logger.info("[Sync] Connecting to GitHub to fetch latest guide updates...")
        all_success = True
        
        for label, (api_url, dest_folder) in self.endpoints.items():
            os.makedirs(dest_folder, exist_ok=True)
            try:
                res = requests.get(api_url, timeout=15)
                if res.status_code != 200:
                    logger.warning(f"[Sync] Failed to fetch {label} list. Code: {res.status_code}")
                    all_success = False
                    continue
                    
                files = res.json()
                downloaded_count = 0
                
                for file_info in files:
                    if file_info['name'].endswith('.json') and file_info['type'] == 'file':
                        file_path = os.path.join(dest_folder, file_info['name'])
                        dl_res = requests.get(file_info['download_url'], timeout=10)
                        if dl_res.status_code == 200:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(dl_res.text)
                            downloaded_count += 1
                
                logger.info(f"[Sync] Downloaded {downloaded_count} files for {label}.")
            except Exception as e:
                logger.error(f"[Sync] Error fetching {label}: {e}")
                all_success = False
                
        if all_success:
            logger.info("[Sync] Guide Cache update completed successfully.")
        else:
            logger.warning("[Sync] Guide Cache update had some errors. Will retry soon.")
            
        return all_success

    def get_existing_formats(self, app_name, url, api_key):
        """Fetches all existing Custom Formats from the Arr API to check for duplicates."""
        try:
            res = requests.get(f"{url}/api/v3/customformat", headers={'X-Api-Key': api_key}, timeout=15)
            if res.status_code == 200:
                # Return a dictionary of {FormatName: FormatID} for easy lookup
                return {fmt['name'].lower(): fmt['id'] for fmt in res.json()}
        except Exception as e:
            logger.error(f"[{app_name}] Failed to fetch existing formats: {e}")
        return {}

    def push_format_to_api(self, app_name, url, api_key, endpoint, payload, existing_formats):
        """
        Smart Push logic: If the format exists, use PUT to update it. 
        If it doesn't exist, use POST to create it.
        """
        item_name = payload.get('name', 'Unknown Item Name')
        lower_name = item_name.lower()
        
        if cfg.DRY_RUN:
            action = "UPDATE (PUT)" if lower_name in existing_formats else "CREATE (POST)"
            logger.info(f"[DRY RUN] Would {action} Format (Name: '{item_name}') in {app_name}")
            return

        try:
            headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}
            
            if lower_name in existing_formats:
                # It exists! We must UPDATE it using the PUT method and its specific ID.
                format_id = existing_formats[lower_name]
                payload['id'] = format_id # Attach the ID to the payload
                res = requests.put(f"{url}{endpoint}/{format_id}", json=payload, headers=headers, timeout=20)
                action_word = "Updated"
            else:
                # It doesn't exist. We CREATE it using the POST method.
                res = requests.post(f"{url}{endpoint}", json=payload, headers=headers, timeout=20)
                action_word = "Created"
                
            if res.status_code in [200, 201, 202]:
                logger.info(f"[{app_name}] Successfully {action_word} format: '{item_name}'")
            else:
                logger.error(f"[{app_name}] Failed to {action_word} '{item_name}'. Code: {res.status_code}")
        except Exception as e:
            logger.error(f"[{app_name}] Connection error during sync for '{item_name}': {e}")

    def push_profile_to_api(self, app_name, url, api_key, endpoint, payload):
        """Standard push for Quality Profiles (We only POST these to avoid breaking user scores)."""
        item_name = payload.get('name', 'Unknown Item Name')
        if cfg.DRY_RUN:
            logger.info(f"[DRY RUN] Would CREATE Profile (Name: '{item_name}') in {app_name}")
            return
            
        try:
            headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}
            # We use POST for profiles. If it exists, Arr app safely rejects it (which is what we want to protect scores).
            res = requests.post(f"{url}{endpoint}", json=payload, headers=headers, timeout=20)
            if res.status_code in [200, 201]:
                logger.info(f"[{app_name}] Successfully Created Profile: '{item_name}'")
            elif res.status_code == 400 and "already exists" in res.text.lower():
                # Silently ignore if profile exists to prevent log spam
                pass
            else:
                logger.error(f"[{app_name}] Failed to sync profile '{item_name}'. Code: {res.status_code}")
        except Exception as e:
            logger.error(f"[{app_name}] Connection error during profile sync for '{item_name}': {e}")

    def load_json_file(self, filepath):
        """Helper function to read a JSON file safely given its full path."""
        if not os.path.exists(filepath):
            logger.warning(f"[Sync] Missing file: {filepath}. Cannot sync this item.")
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[Sync] Invalid JSON inside {filepath}: {e}")
            return None

    def run_sync(self):
        """Main sync logic that processes your personal JSON files on startup."""
        logger.info("Starting Startup Synchronization (Profiles & Formats)...")
        
        base_path = "/config/defaults/3azmeo-profiles"
        
        # --- 1. Custom Formats Sync (SMART UPDATE) ---
        if cfg.SYNC_AMC_FORMAT:
            logger.info("[Sync] Injecting and Updating Custom Formats...")
            
            if cfg.SONARR_ENABLED:
                existing_sonarr_cfs = self.get_existing_formats("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY)
                sonarr_cf_path = os.path.join(base_path, "sonarr/cf/sonarr_custom_formats_export.json")
                sonarr_formats = self.load_json_file(sonarr_cf_path)
                if sonarr_formats:
                    for fmt in sonarr_formats:
                        self.push_format_to_api("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY, "/api/v3/customformat", fmt, existing_sonarr_cfs)
                        
            if cfg.RADARR_ENABLED:
                existing_radarr_cfs = self.get_existing_formats("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY)
                radarr_cf_path = os.path.join(base_path, "radarr/cf/radarr_custom_formats_export.json")
                radarr_formats = self.load_json_file(radarr_cf_path)
                if radarr_formats:
                    for fmt in radarr_formats:
                        self.push_format_to_api("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY, "/api/v3/customformat", fmt, existing_radarr_cfs)

        # --- 2. Quality Profiles Sync (SAFE POST) ---
        if cfg.SYNC_AMC_PROFILE:
            logger.info("[Sync] Injecting Quality Profiles...")
            
            if cfg.SONARR_ENABLED:
                sonarr_prof_path = os.path.join(base_path, "sonarr/score/sonarr_profiles_export.json")
                sonarr_profiles = self.load_json_file(sonarr_prof_path)
                if sonarr_profiles:
                    for prof in sonarr_profiles:
                        self.push_profile_to_api("Sonarr", cfg.SONARR_URL, cfg.SONARR_API_KEY, "/api/v3/qualityprofile", prof)
                        
            if cfg.RADARR_ENABLED:
                radarr_prof_path = os.path.join(base_path, "radarr/score/radarr_profiles_export.json")
                radarr_profiles = self.load_json_file(radarr_prof_path)
                if radarr_profiles:
                    for prof in radarr_profiles:
                        self.push_profile_to_api("Radarr", cfg.RADARR_URL, cfg.RADARR_API_KEY, "/api/v3/qualityprofile", prof)
                        
        logger.info("Startup Synchronization Finished.")