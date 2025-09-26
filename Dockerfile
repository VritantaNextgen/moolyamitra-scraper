# Use an official, specific Python runtime as a parent image
FROM python:3.9-slim

# Set work directory inside the container
WORKDIR /app

# Install system dependencies required for Chrome + certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libnss3 \
    libasound2 \
    libx11-xcb1 \
    libxcomposite1 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Add Google Chrome signing key securely
RUN wget -q -O /usr/share/keyrings/google-linux-signing-key.gpg https://dl.google.com/linux/linux_signing_key.pub

# Add Google Chrome repository
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-signing-key.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

# Install Google Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip/setuptools/wheel to avoid resolver hangs
RUN pip install --upgrade pip setuptools wheel

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Expose port for the app
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
