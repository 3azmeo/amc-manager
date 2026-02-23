# AMC Manager (Arr-Missing-Content Manager) v3.9
> The ultimate, fully automated, zero-intervention manager for your Arr stack (Sonarr, Radarr, qBittorrent).

## 👤 Author & License
**Created by:** 3azmeo (Boumusaed)
**License:** Open Source (MIT). You are free to use, modify, and distribute this software, but you **must** provide credit to the original author (3azmeo).

---

## 🚀 What is AMC Manager?
AMC Manager is a robust, Python-based background engine designed to fix the most common annoyances in media automation. It acts as the "brain" connecting your download client (qBittorrent) and your media managers (Sonarr/Radarr). If you ever deal with stalled torrents, unrecognized release groups, or stuck queues, AMC Manager resolves them completely automatically.

---

## ✨ Detailed Features & Modules

### 🧹 1. Advanced Torrent Cleaner
Tired of torrents getting stuck at 99% or stalling with zero seeds?
* **Strike System:** The Cleaner monitors your qBittorrent client. If a torrent is stalled, it issues a "strike" (saved in a local SQLite database).
* **Auto-Blacklist:** Once a torrent hits the maximum strikes (e.g., 3 strikes), the script deletes it from qBittorrent and tells Sonarr/Radarr to **Blacklist** that specific release so it never downloads the broken file again.

### 🔍 2. The Smart Hunter
* Runs silently in the background on a timer.
* Queries Sonarr and Radarr for missing episodes and movies.
* Automatically triggers an active API search to grab the missing content (especially useful after the Cleaner deletes a bad torrent).

### 🧠 3. Advanced Queue Manager (Smart Batch & Cross-Routing)
Solves the issue of items getting permanently stuck in the Arr queues with yellow warning icons.
* **Smart Batch:** If an item is stuck but recognized, it forces a deep scan to push Sonarr/Radarr to evaluate and import the files.
* **Cross-Arr Routing:** If an item is completely unrecognized (e.g., Sonarr accidentally downloaded a movie), the script removes it from the queue and **Hardlinks** the folder to the manual-import staging area for our Smart Importer to evaluate.

### 📥 4. Smart Importer & Auto-Add Engine
The crown jewel of AMC Manager. It monitors a designated manual-import folder for rejected files.
* **Smart Regex Cleaning:** If a file is named `[example] Overlord - Movie 1.mkv`, the Arr APIs will fail to parse it. The Importer dynamically strips release groups, resolution tags, and brackets to extract the pure title.
* **TVDB/TMDB Lookup:** It queries the APIs using the cleaned name to find the exact database ID.
* **Auto-Add Missing Media:** If the show or movie is not in your Sonarr/Radarr library, the script automatically adds it with your specified default Quality Profile and Root Folder.
* **Safe Hardlinking:** Instead of moving the file (which breaks torrent seeding), it creates a Hardlink in the destination folder, allowing your torrent client to continue seeding uninterrupted.

### 🔄 5. Profile & Custom Format Sync (TRaSH Guides)
Keeps your automation logic up-to-date without destroying your personal preferences.
* **Daily GitHub Fetch:** Automatically downloads the latest Custom Formats and Quality Profiles from the official TRaSH Guides every 24 hours.
* **Smart Update (PUT) Logic:** If a Custom Format already exists in your Arr app, the script updates its regex logic but **leaves your personal scores untouched**. If it's new, it creates it.
* **Local Fallback Cache:** Keeps a local copy of the JSON files in your `/config/defaults` folder so the script can boot and sync even if GitHub is down.

---

## ⚠️ Important Warnings & Prerequisites

1. **Docker Only:** You do not need to build this image manually. Just pull it from Docker Hub.
2. **Volume Paths MUST Match:** For Hardlinks to work, the paths you mount in AMC Manager (e.g., `/data`) **MUST** be identical to the paths used inside your Sonarr, Radarr, and qBittorrent containers.
3. **Unpacking is Not Included:** AMC Manager **does not** extract `.rar` or `.zip` files natively to prevent system overhead and conflicts. You **must** run an external tool (like Unpackerr) alongside this script.

---

## 🛠️ Installation (Docker Compose)
Here is the basic docker-compose.yml template. Adjust the paths and timezone to match your setup.

```yaml
# ==============================================================================
# AMC MANAGER - DOCKER COMPOSE TEMPLATE
# ==============================================================================
services:
  amc-manager:
    image: 3azmeo/amc-manager:latest
    container_name: amc-manager
    restart: unless-stopped
    networks:
      - arr-stack-network
    volumes:
      # Mount your configuration folder (Generates config.yml)
      - /path/to/your/appdata/amc-manager:/config
      
      # Mount your media and download folders (Must match Sonarr/Radarr paths!)
      - /path/to/your/data:/data
    environment:
      # --- qBittorrent Connection ---
      # Use glueutn address if running through VPN
      - QBITTORRENT_URL=${QBITTORRENT_URL}
      - QBITTORRENT_USERNAME=${QBITTORRENT_USERNAME}
      - QBITTORRENT_PASSWORD=${QBITTORRENT_PASSWORD}
      
      # --- Sonarr Configuration ---
      - SONARR_URL=${SONARR_URL}
      - SONARR_API_KEY=${SONARR_API_KEY}
      
      # --- Radarr Configuration ---
      - RADARR_URL=${RADARR_URL}
      - RADARR_API_KEY=${RADARR_API_KEY}
      
      # --- Lidarr Configuration ---
      # Lidarr is fully supported (Cleaner + Searcher)
      - LIDARR_URL=${LIDARR_URL}
      - LIDARR_API_KEY=${LIDARR_API_KEY}
      
      # --- Bazarr Configuration ---
      # Bazarr (Searcher Only)
      # Checks for missing subtitles for Movies & Series
      - BAZARR_URL=${BAZARR_URL}
      - BAZARR_API_KEY=${BAZARR_API_KEY}

networks:
  arr-stack-network:
    external: true

```

## ⚙️ Configuration Guide (config.yml)
When you start the container for the first time, it generates a config.yml file and a defaults folder inside your mapped /config directory. 

**How to edit the config:**
1. Open config.yml in any text editor.
2. Read the English comments above each section. 
3. **Golden Rules:**
   - If you leave a text variable blank (e.g., api_key: ""), the script considers it**Disabled (False)**.
   - If you leave a time variable blank or set it to 0 (e.g., cleaner_timer: 0), the feature is**Disabled (False)**. The minimum value to enable a timer is 1.
4. Save the file and restart the Docker container to apply changes (docker compose restart amc-manager).

---
> *"Set it, forget it, and let AMC Manager do the heavy lifting."*