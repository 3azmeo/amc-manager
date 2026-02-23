# ------------------------------------------------------------------------------
# ARR MISSING CONTENT MANAGER - DOCKERFILE
# ------------------------------------------------------------------------------

# Use a lightweight Python Alpine image to keep the container size small
FROM python:3.11-alpine

# Set the working directory inside the container to /app
WORKDIR /app

# Copy the requirements file first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies without caching to save disk space
RUN pip install --no-cache-dir -r requirements.txt

# --- Create a directory for the default JSON files ---
RUN mkdir -p /defaults

# --- Copy your local defaults folder into the Docker image ---
# This bakes the baseline Custom Formats and Profiles permanently into the image
COPY defaults/ /defaults/

# Copy the baseline defaults into the image as a read-only template
# We will copy this to /config/defaults automatically when the container starts
COPY defaults/ /app/defaults_template/

# Copy the example config file into the container as a fallback
COPY default-config.yml /app/default-config.yml

# COPY ALL PYTHON FILES (*.py) INSTEAD OF JUST main.py
# This ensures config.py, threads.py, and all our split modules are included
COPY *.py .

# Ensure the /data directory exists. 
# This is where we will mount the config.yml and the history.db
RUN mkdir -p /data

# Run the script with unbuffered output (-u) so logs appear immediately in Docker logs without delay
CMD ["python", "-u", "main.py"]

# ------------------------------------------------------------------------------
# BUILT-IN HEALTHCHECK
# ------------------------------------------------------------------------------
# This tells Docker how to test if the container is working correctly.
# It pings the internal Python server on port 8080. If it fails, the container 
# is marked as "unhealthy". You do not need to add this in docker-compose.yml.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/ || exit 1