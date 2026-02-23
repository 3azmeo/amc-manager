# """
# ==============================================================================
# FILE: trash_downloader.py
# ROLE: One-time TRaSH Guides JSON Fetcher (Updated)
# DESCRIPTION:
# Fetches both Custom Formats (CF) AND Quality Profiles (Scores) from the 
# official repository. Organizes them exactly based on Boumusaed's structure.
# ==============================================================================
# """

import os
import requests
import time

# --- Configuration (API Links) ---
SONARR_CF_API = "https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/sonarr/cf"
SONARR_PROFILE_API = "https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/sonarr/quality-profiles"

RADARR_CF_API = "https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/radarr/cf"
RADARR_PROFILE_API = "https://api.github.com/repos/TRaSH-/Guides/contents/docs/json/radarr/quality-profiles"

# --- Destination Folders ---
DEST_SONARR_CF = "./trashguide-cache/sonarr/cf"
DEST_SONARR_SCORE = "./trashguide-cache/sonarr/score"

DEST_RADARR_CF = "./trashguide-cache/radarr/cf"
DEST_RADARR_SCORE = "./trashguide-cache/radarr/score"

def download_files(api_url, dest_folder, label):
    """Fetches JSON files from a specific GitHub directory."""
    print(f"[*] Fetching {label} from GitHub...")
    os.makedirs(dest_folder, exist_ok=True)
    
    try:
        response = requests.get(api_url, timeout=15)
        if response.status_code != 200:
            print(f"[!] Failed to fetch {label}. GitHub API limit reached? (Code {response.status_code})")
            return
            
        files = response.json()
        print(f"[*] Found {len(files)} files. Starting download...")
        
        count = 0
        for file_info in files:
            if file_info['name'].endswith('.json') and file_info['type'] == 'file':
                download_url = file_info['download_url']
                file_path = os.path.join(dest_folder, file_info['name'])
                
                res = requests.get(download_url, timeout=10)
                if res.status_code == 200:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(res.text)
                    count += 1
                    print(f"  -> Downloaded: {file_info['name']}")
                time.sleep(0.1) # Small delay to respect GitHub API limits
                
        print(f"[SUCCESS] Downloaded {count} items to {dest_folder}\n")
    except Exception as e:
        print(f"[!] Error fetching {label}: {e}")

if __name__ == "__main__":
    print("==================================================")
    print(" Baseline Cache Downloader for AMC Manager ")
    print("==================================================")
    
    download_files(SONARR_CF_API, DEST_SONARR_CF, "Sonarr Custom Formats")
    download_files(SONARR_PROFILE_API, DEST_SONARR_SCORE, "Sonarr Quality Profiles")
    
    download_files(RADARR_CF_API, DEST_RADARR_CF, "Radarr Custom Formats")
    download_files(RADARR_PROFILE_API, DEST_RADARR_SCORE, "Radarr Quality Profiles")
    
    print("[*] All done! Your trashguide-cache folder is locked and loaded.")