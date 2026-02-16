# Arr Missing Content Manager (V2)

> **Developed by:** 3azmeo  
> **Version:** 2.0 (The Manager Update)

A powerful, all-in-one Dockerized solution to automate the management of your Arr stack (Sonarr, Radarr, Lidarr). This tool combines a "Missing Content Searcher" with a smart "Torrent Queue Cleaner" to ensure your media library is always up-to-date and free of stuck or dead downloads.

---

## Why use this?

Most Arr applications (Sonarr/Radarr) are great at grabbing releases, but they struggle with two things:
1.  **Exhaustive Searching:** They don't continuously cycle through *all* missing items to find them later.
2.  **Stuck Downloads:** They often leave stalled torrents (0 seeds) or "metadata downloading" errors in your client forever.

**Arr Missing Content Manager** solves both.

### Key Features

#### 1. The Hunter (Searcher)
* **Cyclic Search:** Loops through every single missing item in your library. It won't stop until it finds everything or the cycle resets.
* **Anti-Ban Protection:** Sleeps between every API call to mimic human behavior and prevent private tracker bans.
* **Upgrade Support:** Can search for "Cutoff Unmet" items (e.g., upgrading 720p to 1080p).
* **Smart Database:** Remembers what was searched to avoid redundancy. Wipes itself automatically every 30 days (configurable) to start fresh.
* **Subtitle Hunter:** Integrates with **Bazarr** to find missing subtitles for both Movies and TV Series. It respects your Bazarr profiles and only searches for languages you actually want.

#### 2. The Cleaner (Torrent Manager)
* **Strike System:** Uses a persistent "3-Strike" rule. A slow torrent isn't deleted immediately; it gets chances. If it fails repeatedly, it's removed.
* **Smart Removal:** When a torrent is removed, the tool tells Sonarr/Radarr to **Blacklist** the release and triggers a **Redownload** of a different release automatically.
* **Private Tracker Awareness:**
    * **Auto-Tagging:** Can distinguish between Public and Private torrents.
    * **Safety Mode:** Private torrents are **NEVER deleted** by default. Instead, they are tagged as `amc_obsolete` so you can manage them manually (preserving your ratio).
* **Rules Engine:**
    * Removes **Stalled** downloads (0 seeds).
    * Removes **Slow** downloads (below a specific speed limit).
    * Removes **Metadata Missing** (magnet link stuck).
    * Removes **Failed/Error** states.

---

## Installation

This project is designed to run via Docker Compose.

### 1. docker-compose.yml

Add the following service to your stack. Ensure it is on the same network as your Arrs and qBittorrent.

```yaml
services:
  arr-missing-content:
    image: 3azmeo/arr-missing-content:latest
    container_name: arr-missing-content
    restart: unless-stopped
    networks:
      - arr-stack-network
    volumes:
      - ./data:/data
    environment:
      - LOG_LEVEL=INFO
      - TZ=Asia/Kuwait
      
      # --- General Scheduling ---
      # Runs the search for missing content every X minutes
      - RUN_EVERY=15
      # Runs the qBittorrent cleaner/monitor every X minutes
      - TORRENT_HANDLING_TIMER=20
      
      # --- Searcher Throttling ---
      # How many seconds to wait between each API search call (Anti-Ban)
      - REQUEST_DELAY_SECONDS=5
      # Force a full database reset (restart cycle) after X days
      - MAX_CYCLE_DAYS=30
      
      # --- qBittorrent Connection ---
      # Use glueutn address if running through VPN
      - QBITTORRENT_URL=${QBITTORRENT_URL}
      - QBITTORRENT_USERNAME=${QBITTORRENT_USERNAME}
      - QBITTORRENT_PASSWORD=${QBITTORRENT_PASSWORD}
      
      # --- Cleaner: Feature Toggles (true/false) ---
      # Master switch for the cleaner module
      - ENABLE_TORRENT_HANDLING=true
      # If true, it will NOT delete anything, just log what it WOULD do
      - DRY_RUN=true
      
      # Remove torrents with bad files or error states
      - TORRENT_HANDLING_REMOVE_BAD_FILES=true
      - TORRENT_HANDLING_REMOVE_FAILED_DOWNLOAD=true
      # Remove torrents stuck at "Downloading Metadata"
      - TORRENT_HANDLING_REMOVE_METADATA_MISSING=true
      # Remove torrents with 0 seeds (Stalled)
      - TORRENT_HANDLING_REMOVE_STALLED=true
      # Remove slow torrents (speed limit defined below)
      - TORRENT_HANDLING_REMOVE_SLOW=true
      # Remove torrents NOT found in Arrs history (Orphans). 
      # CAUTION: Set to false if you use manual imports often.
      - TORRENT_HANDLING_REMOVE_ORPHANS=false
      
      # --- Cleaner: Logic & Thresholds ---
      # How many "Strikes" (checks) before deleting a bad torrent?
      - TORRENT_HANDLING_MAX_STRIKES=3
      # Minimum speed in KB/s. Below this = Strike.
      - TORRENT_HANDLING_REMOVE_SLOW_MIN_SPEED=100
      
      # --- Cleaner: Timeouts (Minutes) ---
      # How many minutes to wait for Metadata before giving a strike
      - TIMEOUT_METADATA_MINUTES=15
      # How many minutes to wait for Stalled (0 seeds) before giving a strike
      - TIMEOUT_STALLED_MINUTES=15

      # --- Cleaner: Tags & Protection ---
      # Comma separated tags for Private Trackers.
      # These will NOT be deleted, but tagged as obsolete.
      - TORRENT_HANDLING_PRIVATE_TRACKER_TAGS=private,ipt,tl
      # The tag to apply to Private torrents when they fail checks (instead of deleting)
      - TORRENT_HANDLING_OBSOLETE_TAG=private-trackers
      # Comma separated tags. If a torrent has this tag, it is NEVER touched.
      - TORRENT_HANDLING_PROTECTED_TAG=protected,Keep,Upload
      
      # --- Sonarr Configuration ---
      - SONARR_URL=${SONARR_URL}
      - SONARR_API_KEY=${SONARR_API_KEY}
      - SONARR_LIMIT=10                # Items to search per run
      - SONARR_CUTOFF_LIMIT=0          # 0=Disabled. >0 means search for upgrades.
      
      # --- Radarr Configuration ---
      - RADARR_URL=${RADARR_URL}
      - RADARR_API_KEY=${RADARR_API_KEY}
      - RADARR_LIMIT=10
      - RADARR_CUTOFF_LIMIT=0
      
      # --- Lidarr Configuration ---
      # Lidarr is fully supported (Cleaner + Searcher)
      - LIDARR_URL=${LIDARR_URL}
      - LIDARR_API_KEY=${LIDARR_API_KEY}
      - LIDARR_LIMIT=10
      - LIDARR_CUTOFF_LIMIT=0
      
      # --- Bazarr Configuration ---
      # Bazarr (Searcher Only)
      # Checks for missing subtitles for Movies & Series
      - BAZARR_URL=${BAZARR_URL}
      - BAZARR_API_KEY=${BAZARR_API_KEY}

networks:
  arr-stack-network:
    external: true
```

---

## Configuration Guide

### General Settings
* `RUN_EVERY`: Interval (minutes) for the Searcher to find missing media.
* `TORRENT_HANDLING_TIMER`: Interval (minutes) for the Cleaner to check qBittorrent.
* `DRY_RUN`: If set to `true`, the logs will show what *would* happen, but no files will be deleted. **Recommended for first run.**

### The Cleaner Rules (Torrent Handling)
The Cleaner uses a **Strike System**. It does not delete a torrent the first time it sees an issue.
1.  **Strike 1:** Issue detected (e.g., speed < 100KB/s). Recorded in DB.
2.  **Strike 2:** Issue persists in the next check.
3.  **Strike 3:** Max strikes reached -> **Action Taken.**

#### Action Logic:
* **Public Torrent:** The torrent is removed from qBittorrent and the files are deleted. Sonarr/Radarr is notified to **Blocklist** the release and search for a new one.
* **Private Torrent:** If the torrent has one of the `PRIVATE_TRACKER_TAGS`, it is **NOT DELETED**. Instead, it is tagged with `amc_obsolete`. You can then filter by this tag in qBittorrent and decide what to do manually.

### Supported Applications
* **Sonarr** (TV Shows) - Fully Supported (Search + Clean)
* **Radarr** (Movies) - Fully Supported (Search + Clean)
* **Lidarr** (Music) - Fully Supported (Search + Clean)
* **Bazarr** (Subtitles) - Supported (Searcher Only). It checks for Movies and Series that have a file but report missing subtitles (based on your Bazarr profiles) and triggers a search for them.

---

## FAQ & Troubleshooting

### 1. How does it distinguish Private vs Public?
It uses the tags defined in `TORRENT_HANDLING_PRIVATE_TRACKER_TAGS`. If a torrent in qBittorrent has the tag `private` (usually added by Prowlarr), this tool treats it as "Safe/Private".

### 2. Will it delete my library files?
**No.** This tool interacts with the *Download Client* (qBittorrent) and the *Arr Queue*.
If you use **Hardlinks** (recommended), deleting a file from the `downloads` folder does **not** delete the imported file in your `media` library. They are safe.

### 3. What is "Orphans"?
Orphans are downloads in qBittorrent that Sonarr/Radarr do not recognize (not in their history).
* If `TORRENT_HANDLING_REMOVE_ORPHANS=true`: It will delete them.
* If `false` (Default): It ignores them. Keep this `false` if you manually download items outside of the Arr stack.

---

## License

**MIT License**

> Copyright (c) 2025 3azmeo

Permission is hereby granted, free of charge, to any person obtaining a copy of this software... (See full MIT license).

*You are free to use and modify this project, but please attribute the original work to 3azmeo.*
