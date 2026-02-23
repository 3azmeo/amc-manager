# """
# ==============================================================================
# FILE: config.py
# ROLE: Dynamic Real-Time Configuration Manager
# DESCRIPTION:
# Reads config.yml in real-time. Handles missing values safely.
# Logic:
# - Missing Key OR Empty Value -> Returns False (Feature Disabled).
# - Timer set to 0 -> Returns False (Disabled to prevent CPU spikes).
# - Logs exact changes when file is modified.
# ==============================================================================
# """

import os
import yaml
import logging
import shutil
import time

class ConfigManager:
    """
    Manages configuration dynamically. Checks file modification time
    to reload settings instantly without restarting the container.
    """
    def __init__(self):
        # Paths setup
        self.config_path = "/config/config.yml"
        self.default_path = "/app/default-config.yml"
        
        self.raw_cfg = {}
        self.last_mtime = 0
        
        self.ensure_default_config()
        self.reload()

    def ensure_default_config(self):
        """Creates a default config file if one is missing."""
        if not os.path.exists(self.config_path):
            print(f"WARNING: Config file not found at {self.config_path}. Creating a default one...")
            try:
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                if os.path.exists(self.default_path):
                    shutil.copy(self.default_path, self.config_path)
                    print("SUCCESS: Default config.yml has been generated! Please edit it.")
                else:
                    print("ERROR: Default template not found inside container!")
            except Exception as e:
                print(f"ERROR: Failed to create default config: {e}")

    def reload(self):
        """
        Reads the YAML file ONLY if modified.
        Logs detailed changes (Old Value vs New Value).
        """
        if not os.path.exists(self.config_path):
            return

        current_mtime = os.path.getmtime(self.config_path)
        
        if current_mtime != self.last_mtime:
            try:
                with open(self.config_path, 'r') as f:
                    new_cfg = yaml.safe_load(f) or {}
                
                # --- TIMEZONE SETUP ---
                tz = new_cfg.get('timezone', 'Asia/Kuwait')
                os.environ['TZ'] = tz
                if hasattr(time, 'tzset'):
                    time.tzset()

                # --- CHANGE LOGGING ---
                if self.last_mtime != 0:
                    changes_found = False
                    current_time = time.strftime('%Y-%m-%d %H:%M:%S')
                    print(f"\n[{current_time}] CONFIG UPDATED: Changes detected in config.yml")
                    
                    # Check for added or changed keys
                    for key, new_value in new_cfg.items():
                        old_value = self.raw_cfg.get(key)
                        if key not in self.raw_cfg:
                            print(f"  -> ADDED: '{key}' = {new_value}")
                            changes_found = True
                        elif old_value != new_value:
                            print(f"  -> CHANGED: '{key}' from '{old_value}' to '{new_value}'")
                            changes_found = True
                            
                    # Check for removed keys
                    for key in self.raw_cfg.keys():
                        if key not in new_cfg:
                            print(f"  -> REMOVED: '{key}'")
                            changes_found = True
                            
                    if not changes_found:
                        print("  -> File saved, but no values changed.")
                    print("-" * 60)
                    
                self.raw_cfg = new_cfg
                self.last_mtime = current_mtime
            except Exception as e:
                print(f"ERROR: Failed to parse {self.config_path}: {e}")

    def get_setting(self, enable_key, val_key, expected_type=str):
        """
        Strict Logic for retrieving settings:
        1. If 'enable_key' is missing, commented out, or False -> RETURN False.
        2. If 'val_key' is missing or Empty -> RETURN False.
        3. If 'val_key' is 0 (for Ints) -> RETURN False (Safety).
        """
        self.reload() 
        
        # Check if the feature switch is ON
        is_enabled = self.raw_cfg.get(enable_key, False)
        if not is_enabled:
            return False
            
        # Get the actual value
        val = self.raw_cfg.get(val_key)
        
        # If value is None (missing) or Empty String -> Disable it
        if val is None or val == '':
            return False
            
        if expected_type == int:
            try:
                val = int(val)
                # SAFETY RULE: If timer is 0, disable it to prevent CPU 100% usage
                if val <= 0:
                    return False 
            except ValueError:
                return False
                
        elif expected_type == list:
            if isinstance(val, str):
                val = [x.strip() for x in val.split(',')]
            if not val:
                return False
                
        return val

    # ==========================================================================
    # DYNAMIC PROPERTIES
    # ==========================================================================

    # --- Core Settings ---
    @property
    def DRY_RUN(self): self.reload(); return self.raw_cfg.get('dry_run', True)
    @property
    def LOG_LEVEL(self): self.reload(); return self.raw_cfg.get('log_level', 'INFO')
    
    # --- Environment Variables (Arr Apps) ---
    @property
    def QBIT_URL(self): return os.getenv("QBITTORRENT_URL", "http://gluetun:8080")
    @property
    def QBIT_USER(self): return os.getenv("QBITTORRENT_USERNAME", "admin")
    @property
    def QBIT_PASS(self): return os.getenv("QBITTORRENT_PASSWORD", "adminadmin")

    @property
    def SONARR_URL(self): return os.getenv("SONARR_URL")
    @property
    def SONARR_API_KEY(self): return os.getenv("SONARR_API_KEY")
    @property
    def SONARR_ENABLED(self): return bool(self.SONARR_URL and self.SONARR_API_KEY)

    @property
    def RADARR_URL(self): return os.getenv("RADARR_URL")
    @property
    def RADARR_API_KEY(self): return os.getenv("RADARR_API_KEY")
    @property
    def RADARR_ENABLED(self): return bool(self.RADARR_URL and self.RADARR_API_KEY)

    @property
    def LIDARR_URL(self): return os.getenv("LIDARR_URL")
    @property
    def LIDARR_API_KEY(self): return os.getenv("LIDARR_API_KEY")
    @property
    def LIDARR_ENABLED(self): return bool(self.LIDARR_URL and self.LIDARR_API_KEY)

    @property
    def BAZARR_URL(self): return os.getenv("BAZARR_URL")
    @property
    def BAZARR_API_KEY(self): return os.getenv("BAZARR_API_KEY")
    @property
    def BAZARR_ENABLED(self): return bool(self.BAZARR_URL and self.BAZARR_API_KEY)

    # --- Timers & Toggles ---
    @property
    def SEARCH_RUN_EVERY(self): return self.get_setting('enable_run_every_minutes', 'run_every_minutes', int) or 15
    @property
    def CLEANER_RUN_EVERY(self): return self.get_setting('enable_torrent_handling_timer', 'torrent_handling_timer_minutes', int) or 20
    @property
    def ENABLE_TORRENT_HANDLING(self): self.reload(); return self.raw_cfg.get('enable_cleaner', True)

    @property
    def PRIVATE_TAGS(self): return self.get_setting('enable_private_tracker_tags', 'private_tracker_tags', list) or ['private']
    @property
    def PROTECTED_TAGS(self): return self.get_setting('enable_protected_tags', 'protected_tags', list) or ['protected', 'Keep']
    @property
    def OBSOLETE_TAG(self): return self.get_setting('enable_obsolete_tag', 'obsolete_tag', str) or "amc_obsolete"

    @property
    def MAX_STRIKES(self): return self.get_setting('enable_max_strikes', 'max_strikes', int) or 3
    @property
    def MIN_SPEED_KB(self): return self.get_setting('enable_remove_slow_min_speed', 'remove_slow_min_speed_kbps', int) or 100
    @property
    def MIN_SPEED_BYTES(self): return self.MIN_SPEED_KB * 1024

    @property
    def RM_BAD_FILES(self): self.reload(); return self.raw_cfg.get('enable_remove_bad_files', True)
    @property
    def RM_FAILED(self): self.reload(); return self.raw_cfg.get('enable_remove_failed_download', True)
    @property
    def RM_META_MISSING(self): self.reload(); return self.raw_cfg.get('enable_remove_metadata_missing', True)
    @property
    def RM_STALLED(self): self.reload(); return self.raw_cfg.get('enable_remove_stalled', True)
    @property
    def RM_SLOW(self): self.reload(); return self.raw_cfg.get('enable_remove_slow', True)
    @property
    def RM_ORPHANS(self): self.reload(); return self.raw_cfg.get('enable_remove_orphans', False)

    @property
    def TIMEOUT_METADATA(self): return self.get_setting('enable_timeout_metadata_minutes', 'timeout_metadata_minutes', int) or 15
    @property
    def TIMEOUT_STALLED(self): return self.get_setting('enable_timeout_stalled_minutes', 'timeout_stalled_minutes', int) or 15
    @property
    def REQUEST_DELAY(self): return self.get_setting('enable_request_delay_seconds', 'request_delay_seconds', int) or 5
    @property
    def MAX_CYCLE_DAYS(self): return self.get_setting('enable_max_cycle_days', 'max_cycle_days', int) or 30

    @property
    def SONARR_LIMIT(self): return self.get_setting('enable_sonarr_limits', 'sonarr_search_limit', int) or 10
    @property
    def SONARR_CUTOFF(self): return self.get_setting('enable_sonarr_limits', 'sonarr_cutoff_limit', int) or 0
    @property
    def RADARR_LIMIT(self): return self.get_setting('enable_radarr_limits', 'radarr_search_limit', int) or 10
    @property
    def RADARR_CUTOFF(self): return self.get_setting('enable_radarr_limits', 'radarr_cutoff_limit', int) or 0
    @property
    def LIDARR_LIMIT(self): return self.get_setting('enable_lidarr_limits', 'lidarr_search_limit', int) or 10
    @property
    def LIDARR_CUTOFF(self): return self.get_setting('enable_lidarr_limits', 'lidarr_cutoff_limit', int) or 0

    @property
    def ENABLE_SMART_BATCH(self): self.reload(); return self.raw_cfg.get('enable_smart_batch_dissector', False)
    @property
    def ENABLE_CROSS_ARR(self): self.reload(); return self.raw_cfg.get('enable_cross_arr_routing', False)

    @property
    def ENABLE_MANUAL_IMPORT(self): self.reload(); return self.raw_cfg.get('enable_manual_import_auto', False)
    @property
    def MANUAL_IMPORT_INTERVAL(self): return self.get_setting('enable_manual_import_scan_interval', 'manual_import_scan_interval_minutes', int) or 5
    @property
    def MANUAL_IMPORT_PATH(self): return self.get_setting('enable_manual_import_location', 'manual_import_location', str) or "/data/manual-import"
    @property
    def FAILED_RETENTION_MINS(self): return self.get_setting('enable_failed_retention_minutes', 'failed_retention_minutes', int) or 180

    @property
    def SYNC_AMC_PROFILE(self): self.reload(); return self.raw_cfg.get('enable_make_amc_profile', False)
    @property
    def SYNC_AMC_FORMAT(self): self.reload(); return self.raw_cfg.get('enable_sync_custom_AMC_format', False)
    @property
    def SYNC_AMC_SCORE(self): self.reload(); return self.raw_cfg.get('enable_sync_amc_score', False)

    # ==========================================================================
    # AUTO-ADD SETTINGS (V3.4) - STRING BASED
    # ==========================================================================
    @property
    def ENABLE_AUTO_ADD(self): self.reload(); return self.raw_cfg.get('enable_auto_add', False)
    
    # --- Sonarr ---
    @property
    def AUTO_ADD_SONARR_STD_PROFILE(self): self.reload(); return self.raw_cfg.get('auto_add_sonarr_standard_profile_name', 'Any')
    @property
    def AUTO_ADD_SONARR_STD_PATH(self): self.reload(); return self.raw_cfg.get('auto_add_sonarr_standard_root_folder', '/data/tv-shows')
    
    @property
    def AUTO_ADD_SONARR_ANIME_PROFILE(self): self.reload(); return self.raw_cfg.get('auto_add_sonarr_anime_profile_name', 'Any')
    @property
    def AUTO_ADD_SONARR_ANIME_PATH(self): self.reload(); return self.raw_cfg.get('auto_add_sonarr_anime_root_folder', '/data/anime/series')

    # --- Radarr ---
    @property
    def AUTO_ADD_RADARR_STD_PROFILE(self): self.reload(); return self.raw_cfg.get('auto_add_radarr_standard_profile_name', 'Any')
    @property
    def AUTO_ADD_RADARR_STD_PATH(self): self.reload(); return self.raw_cfg.get('auto_add_radarr_standard_root_folder', '/data/movies')
    
    @property
    def AUTO_ADD_RADARR_ANIME_PROFILE(self): self.reload(); return self.raw_cfg.get('auto_add_radarr_anime_profile_name', 'Any')
    @property
    def AUTO_ADD_RADARR_ANIME_PATH(self): self.reload(); return self.raw_cfg.get('auto_add_radarr_anime_root_folder', '/data/anime/movies')

    # --- TRaSH Sync Settings ---
    @property
    def ENABLE_TRASH_GUIDE_SYNC(self): self.reload(); return self.raw_cfg.get('enable_trash_guide_sync', False)

    @property
    def ENABLE_BUILTIN_EXTRACTION(self): self.reload(); return self.raw_cfg.get('enable_builtin_extraction', False)
    
cfg = ConfigManager()
DB_PATH = "/config/history.db"