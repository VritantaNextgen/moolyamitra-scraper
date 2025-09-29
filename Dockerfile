# Use an official, specific Python runtime as a parent image for reproducibility.
FROM python:3.9-slim

# Set the working directory inside the container.
WORKDIR /app

# --- CORRECTED & MODERNIZED: Install system dependencies for Google Chrome ---
# This version uses --no-install-recommends to reduce image size and adds a more thorough cleanup phase.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    gnupg \
    ca-certificates \
    # Download the Google Chrome signing key, de-armor it, and save it to the trusted keyrings directory
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg \
    # Add the Google Chrome repository, signed by the key we just added
    && sh -c 'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    # Update package lists again to include the new repository
    && apt-get update \
    # Install Google Chrome without recommended packages
    && apt-get install -y --no-install-recommends google-chrome-stable \
    # --- The Cleanup Section ---
    # Remove the repository and key files as they are no longer needed after installation
    && rm -f /etc/apt/sources.list.d/google-chrome.list \
    && rm -f /usr/share/keyrings/google-chrome-keyring.gpg \
    # Clean up all apt caches and lists to save space
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container.
COPY requirements.txt .

# Install the Python dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application's code into the container.
COPY main.py .

# Expose the port the app runs on.
EXPOSE 8000

# Define the command to run your app.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

