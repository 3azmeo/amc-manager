# ==============================================================================
# FILE: main.py
# PURPOSE: The General Manager. This is the main entry point of the application.
#          It does not contain heavy logic. It only initializes the database,
#          starts the background workers (threads), and keeps the container alive.
# VARIABLES/DEPENDENCIES: Requires all other local modules to be imported.
#          In V4, it will also initialize the Web UI server.
# ==============================================================================

import time
import logging
import threading

# Import the specific main functions and classes from our local files
# This way, the code below works perfectly without modifications
from database import init_db
from sync_mgr import ProfileSyncManager
from webui import healthcheck_thread
from threads import searcher_thread, cleaner_thread, advanced_queue_thread, manual_import_thread
from threads import trash_guide_sync_thread


# ==============================================================================
# MAIN ENTRY POINT (Start of Script)
# ==============================================================================
def main():
    logging.info("Starting Arr Missing Content Manager Engine...")
    
    # Step 1: Initialize memory database
    init_db()

    # Step 2: Run Startup Configuration Sync (Profiles, Formats, Scores)
    # This runs ONCE before anything else.
    sync_manager = ProfileSyncManager()
    sync_manager.run_sync()

    # Step 3: Start the Docker Healthcheck background server
    t_health = threading.Thread(target=healthcheck_thread, name="Healthcheck", daemon=True)
    t_health.start()

    # Step 4: Start the Hunter (Missing Searcher) background process
    t_search = threading.Thread(target=searcher_thread, name="Searcher", daemon=True)
    t_search.start()

    # Step 5: Start the Torrent Cleaner background process
    t_clean = threading.Thread(target=cleaner_thread, name="Cleaner", daemon=True)
    t_clean.start()

    # Step 6: Start the Advanced Queue background process
    t_queue = threading.Thread(target=advanced_queue_thread, name="AdvancedQueue", daemon=True)
    t_queue.start()

    # Step 7: Start the Manual Importer background process
    t_import = threading.Thread(target=manual_import_thread, name="ManualImport", daemon=True)
    t_import.start()

    # Step 8: Start the TRaSH Guide Sync background process
    t_sync = threading.Thread(target=trash_guide_sync_thread, daemon=True)
    t_sync.start()

    # Step 9: Keep the main program alive indefinitely
    while True:
        time.sleep(1)
if __name__ == "__main__":
    main()