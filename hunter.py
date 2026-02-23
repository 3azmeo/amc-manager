"""
==============================================================================
FILE: hunter.py
ROLE: The Missing Content Hunter (Loud & Verbose Version)
DESCRIPTION:
Talks to the Arrs (Sonarr, Radarr, Lidarr, Bazarr), checks what media or 
subtitles are missing, and triggers API search commands to find them.
Now it extracts readable names (Movies, Series, Episodes) instead of just 
IDs, making the logs highly detailed and understandable.
==============================================================================
"""

import time
import requests
import logging
import sqlite3
from datetime import timedelta, datetime

# Import the dynamic config manager and static DB PATH
from config import cfg, DB_PATH

# Import specific database functions to read/write search history
from database import wipe_table, get_searched_ids, add_searched_id

# Initialize the logger for this specific module
logger = logging.getLogger(__name__)

# ==============================================================================
# MODULE 2: THE HUNTER (MISSING CONTENT SEARCHER)
# ==============================================================================
class MissingSearcher:
    """Finds missing episodes/movies and tells the Arrs to search for them."""
    
    def check_safety_net(self, table_name):
        """Deletes the search memory if it gets too old."""
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(f"SELECT timestamp FROM {table_name} ORDER BY timestamp ASC LIMIT 1")
            row = c.fetchone()
            conn.close()
            if row:
                oldest = datetime.fromisoformat(row[0])
                if datetime.now() - oldest > timedelta(days=cfg.MAX_CYCLE_DAYS):
                    wipe_table(table_name)
                    logger.info(f"[{table_name}] Memory cleared (Exceeded max cycle days).")
        except Exception:
            pass

    def fetch_missing_items(self, app_name, url, api_key, endpoint):
        """
        Downloads the list of missing items from the Arr API.
        Extracts both the ID and a Readable Title so the logs look nice.
        """
        try:
            res = requests.get(f"{url}{endpoint}", headers={'X-Api-Key': api_key}, timeout=30)
            data = res.json()
            
            # The API might return a list directly, or a dictionary containing 'records'
            records = data.get('records', []) if isinstance(data, dict) else data
            items = []
            
            for i in records:
                item_id = i.get('id')
                if not item_id: continue

                # Build a readable title based on which app we are asking
                if app_name == "Sonarr":
                    series_title = i.get('series', {}).get('title', 'Unknown Series')
                    season = i.get('seasonNumber', 0)
                    ep = i.get('episodeNumber', 0)
                    # Example format: "Game of Thrones - S01E01"
                    title = f"{series_title} - S{season:02d}E{ep:02d}"
                elif app_name == "Radarr":
                    title = i.get('title', 'Unknown Movie')
                elif app_name == "Lidarr":
                    artist = i.get('artist', {}).get('artistName', 'Unknown Artist')
                    album = i.get('title', 'Unknown Album')
                    title = f"{artist} - {album}"
                else:
                    title = str(item_id)

                items.append({'id': item_id, 'title': title})
                
            return items
        except Exception as e:
            logger.error(f"[{app_name}] Failed to fetch items: {e}")
            return []

    def run_cycle(self, app_name):
        """Main loop that finds missing items and triggers searches."""
        if app_name == "Sonarr":
            url, key, limit, cutoff, api_version = cfg.SONARR_URL, cfg.SONARR_API_KEY, cfg.SONARR_LIMIT, cfg.SONARR_CUTOFF, "v3"
        elif app_name == "Radarr":
            url, key, limit, cutoff, api_version = cfg.RADARR_URL, cfg.RADARR_API_KEY, cfg.RADARR_LIMIT, cfg.RADARR_CUTOFF, "v3"
        elif app_name == "Lidarr":
            url, key, limit, cutoff, api_version = cfg.LIDARR_URL, cfg.LIDARR_API_KEY, cfg.LIDARR_LIMIT, cfg.LIDARR_CUTOFF, "v1"
        elif app_name == "Bazarr":
            # Bazarr has a special subtitle search loop
            self.run_bazarr_cycle()
            return
        else:
            return

        self.check_safety_net(f"{app_name.lower()}_searches")
        candidates = []
        
        try:
            if app_name == "Sonarr":
                candidates.extend(self.fetch_missing_items(app_name, url, key, f"/api/{api_version}/wanted/missing?page=1&pageSize=1000&sortKey=airDateUtc&sortDir=desc"))
                if cutoff > 0: candidates.extend(self.fetch_missing_items(app_name, url, key, f"/api/{api_version}/wanted/cutoff?page=1&pageSize=1000"))
            elif app_name == "Lidarr":
                candidates.extend(self.fetch_missing_items(app_name, url, key, f"/api/{api_version}/wanted/missing?page=1&pageSize=1000&sortKey=releaseDate&sortDir=desc"))
                if cutoff > 0: candidates.extend(self.fetch_missing_items(app_name, url, key, f"/api/{api_version}/wanted/cutoff?page=1&pageSize=1000"))
            elif app_name == "Radarr":
                candidates.extend(self.fetch_missing_items(app_name, url, key, "/api/v3/wanted/missing?page=1&pageSize=1000"))
                if cutoff > 0: candidates.extend(self.fetch_missing_items(app_name, url, key, "/api/v3/wanted/cutoff?page=1&pageSize=1000"))
        except Exception:
            return

        # Remove duplicate items by converting the list to a dictionary using ID as the key
        unique_candidates = {c['id']: c for c in candidates}
        
        # Filter out items we already searched for recently
        searched = get_searched_ids(f"{app_name.lower()}_searches")
        target = [item for item in unique_candidates.values() if item['id'] not in searched]
        
        logger.info(f"[{app_name}] Found {len(target)} missing items waiting to be searched.")

        if not target:
            if searched: wipe_table(f"{app_name.lower()}_searches")
            return

        # Take only a small batch based on your limits to prevent bans
        batch = target[:limit]
        headers = {'X-Api-Key': key}
        table = f"{app_name.lower()}_searches"
        
        for item in batch:
            item_id = item['id']
            item_title = item['title']
            
            try:
                payload = {}
                if app_name == "Sonarr": payload = {'name': 'EpisodeSearch', 'episodeIds': [item_id]}
                elif app_name == "Radarr": payload = {'name': 'MoviesSearch', 'movieIds': [item_id]}
                elif app_name == "Lidarr": payload = {'name': 'AlbumSearch', 'albumIds': [item_id]}

                # --- DRY RUN CHECK ---
                if cfg.DRY_RUN:
                    logger.info(f"[DRY RUN] Would trigger Search for: '{item_title}' in {app_name}")
                else:
                    requests.post(f"{url}/api/{api_version}/command", json=payload, headers=headers, timeout=30)
                    logger.info(f"[{app_name}] Triggered Search for: '{item_title}'")
                
                # Remember that we searched for this ID
                add_searched_id(table, item_id)
                
                # Wait a few seconds to avoid angering Private Trackers
                time.sleep(cfg.REQUEST_DELAY)
            except Exception as e:
                logger.error(f"[{app_name}] Failed to search for '{item_title}': {e}")

    def run_bazarr_cycle(self):
        """Special logic for Bazarr Subtitle Searching with detailed logs."""
        logger.info("[Bazarr] Starting Subtitle Search Cycle...")
        headers = {'X-Api-Key': cfg.BAZARR_API_KEY}
        
        # --- MOVIES SUBTITLE SEARCH ---
        try:
            res = requests.get(f"{cfg.BAZARR_URL}/api/movies", headers=headers, timeout=30)
            if res.status_code == 200:
                movies = res.json().get('data', [])
                
                # Find movies that exist on disk but lack subtitles
                missing_movies = []
                for m in movies:
                    if m.get('has_file') and m.get('missing_subtitles', 0) > 0:
                        missing_movies.append({'id': m['radarrId'], 'title': m.get('title', 'Unknown Movie')})
                
                searched = get_searched_ids("bazarr_searches")
                target = [m for m in missing_movies if m['id'] not in searched]
                
                logger.info(f"[Bazarr] Found {len(target)} Movies missing subtitles.")
                
                for movie in target[:5]: # Search 5 movies at a time
                    try:
                        payload = {'name': 'movies_search', 'ids': [movie['id']]}
                        
                        if cfg.DRY_RUN:
                            logger.info(f"[DRY RUN] Would trigger Sub Search for Movie: '{movie['title']}'")
                        else:
                            requests.post(f"{cfg.BAZARR_URL}/api/command", json=payload, headers=headers, timeout=30)
                            logger.info(f"[Bazarr] Searching Subs for Movie: '{movie['title']}'")
                            
                        add_searched_id("bazarr_searches", movie['id'])
                        time.sleep(cfg.REQUEST_DELAY)
                    except Exception as e:
                        logger.error(f"[Bazarr] Movie Search Error for {movie['title']}: {e}")
        except Exception as e:
            logger.error(f"[Bazarr] API Connection Error: {e}")

        # --- TV SERIES SUBTITLE SEARCH ---
        try:
            res = requests.get(f"{cfg.BAZARR_URL}/api/series", headers=headers, timeout=30)
            if res.status_code == 200:
                all_series = res.json().get('data', [])
                target_series = [s for s in all_series if s.get('missing_subtitles', 0) > 0]
                
                count_searched_episodes = 0
                
                for series in target_series:
                    if count_searched_episodes >= 10: break # Max 10 episodes per cycle
                    
                    series_id = series['id']
                    series_title = series.get('title', 'Unknown Series')
                    
                    ep_res = requests.get(f"{cfg.BAZARR_URL}/api/episodes?seriesId={series_id}", headers=headers, timeout=20)
                    if ep_res.status_code == 200:
                        episodes = ep_res.json().get('data', [])
                        
                        missing_eps = []
                        for e in episodes:
                            if e.get('has_file') and e.get('missing_subtitles', 0) > 0:
                                ep_name = f"{series_title} - S{e.get('seasonNumber', 0):02d}E{e.get('episodeNumber', 0):02d}"
                                missing_eps.append({'id': e['id'], 'title': ep_name})
                        
                        searched_eps = get_searched_ids("bazarr_searches")
                        real_targets = [ep for ep in missing_eps if ep['id'] not in searched_eps]
                        
                        for ep in real_targets:
                            if count_searched_episodes >= 10: break
                            try:
                                payload = {'name': 'episodes_search', 'ids': [ep['id']]}
                                
                                if cfg.DRY_RUN:
                                    logger.info(f"[DRY RUN] Would trigger Sub Search for Episode: '{ep['title']}'")
                                else:
                                    requests.post(f"{cfg.BAZARR_URL}/api/command", json=payload, headers=headers, timeout=30)
                                    logger.info(f"[Bazarr] Searching Subs for Episode: '{ep['title']}'")
                                    
                                add_searched_id("bazarr_searches", ep['id'])
                                time.sleep(cfg.REQUEST_DELAY)
                                count_searched_episodes += 1
                            except Exception as e:
                                logger.error(f"[Bazarr] Episode Search Error for {ep['title']}: {e}")
        except Exception as e:
            logger.error(f"[Bazarr] Series Connection Error: {e}")