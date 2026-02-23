# """
# ==============================================================================
# FILE: threads.py
# ROLE: Background Timers & Workers
# DESCRIPTION:
# Background loops that check the config every second (Micro-nap).
# Added Error Catching: If any thread crashes, it will now loudly print the 
# EXACT error to the console so we can debug it immediately.
# ==============================================================================
# """

import time
import schedule
import logging
import traceback # NEW: Helps print the exact line of the error

from config import cfg
from hunter import MissingSearcher
from cleaner import TorrentCleaner
from queue_manager import QueueManager
from importer import ManualImporter

logger = logging.getLogger(__name__)

def searcher_thread():
    """Runs the Hunter module."""
    searcher = MissingSearcher()
    logger.info("Searcher Thread Started.")
    last_run = 0
    
    while True:
        try:
            schedule.run_pending()
            now = time.time()
            if now - last_run >= (cfg.SEARCH_RUN_EVERY * 60) or last_run == 0:
                logger.info("--- Searcher Cycle Started ---")
                if cfg.SONARR_ENABLED: searcher.run_cycle("Sonarr")
                if cfg.RADARR_ENABLED: searcher.run_cycle("Radarr")
                if cfg.LIDARR_ENABLED: searcher.run_cycle("Lidarr")
                if cfg.BAZARR_ENABLED: searcher.run_cycle("Bazarr")
                last_run = time.time()
            time.sleep(1)
        except Exception as e:
            # NEW: Loudly announce the crash
            logger.error(f"[CRASH] Searcher Thread failed: {e}")
            time.sleep(60)

def cleaner_thread():
    """Runs the Torrent Cleaner module."""
    cleaner = TorrentCleaner()
    logger.info("Cleaner Thread Started.")
    last_run = 0
    
    while True:
        try:
            if cfg.ENABLE_TORRENT_HANDLING:
                now = time.time()
                if now - last_run >= (cfg.CLEANER_RUN_EVERY * 60) or last_run == 0:
                    logger.info("--- Cleaner Cycle Started ---")
                    cleaner.run_cleaner_cycle()
                    last_run = time.time()
            else:
                last_run = 0
            time.sleep(1)
        except Exception as e:
            logger.error(f"[CRASH] Cleaner Thread failed: {e}")
            time.sleep(60)

def advanced_queue_thread():
    """Runs the Smart Batch & Routing module."""
    queue_mgr = QueueManager()
    logger.info("Advanced Queue Thread Started.")
    last_run = 0
    
    while True:
        try:
            if cfg.ENABLE_SMART_BATCH or cfg.ENABLE_CROSS_ARR:
                now = time.time()
                if now - last_run >= (cfg.CLEANER_RUN_EVERY * 60) or last_run == 0:
                    queue_mgr.run_cycle()
                    last_run = time.time()
            else:
                last_run = 0
            time.sleep(1)
        except Exception as e:
            logger.error(f"[CRASH] Advanced Queue Thread failed: {e}")
            time.sleep(60)

def manual_import_thread():
    """Runs the Manual Importer module."""
    importer = ManualImporter()
    logger.info("Manual Import Thread Started.")
    last_run = 0
    
    while True:
        try:
            if cfg.ENABLE_MANUAL_IMPORT:
                now = time.time()
                if now - last_run >= (cfg.MANUAL_IMPORT_INTERVAL * 60) or last_run == 0:
                    importer.run_cycle()
                    last_run = time.time()
            else:
                last_run = 0 
            time.sleep(1)
        except Exception as e:
            # NEW: Loudly announce the crash and print the traceback
            logger.error(f"[CRASH] Manual Import Thread failed: {e}")
            traceback.print_exc() # Prints exactly which line failed
            time.sleep(60)

def trash_guide_sync_thread():
    """
    Runs the Guide Downloader in the background.
    Logic: Tries to update every 24 hours. If it fails (no internet), it retries every 5 minutes.
    Once successful, the next update is exactly 24 hours from the success time.
    """
    # Import locally inside the thread to avoid circular dependencies
    from sync_mgr import ProfileSyncManager 
    sync_manager = ProfileSyncManager()
    
    logger.info("Guide Sync Thread Started.")
    last_success = 0
    retry_mode = False
    
    # Run the setup once when the thread starts to ensure folders exist
    sync_manager.setup_directories()
    
    while True:
        try:
            if cfg.ENABLE_TRASH_GUIDE_SYNC:
                now = time.time()
                # 300 seconds = 5 minutes (Retry Mode)
                # 86400 seconds = 24 hours (Normal Mode)
                interval = 300 if retry_mode else 86400 
                
                # If time has passed, or it has NEVER run before (last_success == 0)
                if now - last_success >= interval or last_success == 0:
                    logger.info("--- Guide Cache Update Cycle Started ---")
                    
                    success = sync_manager.update_trash_guide_cache()
                    
                    if success:
                        last_success = time.time() # Lock in the success time
                        retry_mode = False # Back to 24-hour normal mode
                    else:
                        last_success = time.time() # Reset timer to try again in 5 mins
                        retry_mode = True # Activate panic/retry mode
            else:
                last_success = 0 # Sleep mode if turned off in config
                
            time.sleep(1)
        except Exception as e:
            logger.error(f"[CRASH] Guide Sync Thread failed: {e}")
            time.sleep(60)