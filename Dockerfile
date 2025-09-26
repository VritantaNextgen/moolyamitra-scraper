# Use an official, specific Python runtime as a parent image for reproducibility.
# 'slim' is a good choice for keeping the image size smaller.
FROM python:3.9-slim

# Set the working directory inside the container. All subsequent commands will run from here.
WORKDIR /app

# Install system dependencies required for Google Chrome and its driver.
# The backslash "\" at the end of each line tells Docker this is a single, multi-line command.
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    gnupg \
    # Add Google Chrome's official repository to the system's sources
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    # Install Google Chrome Stable
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    # Clean up the apt cache to reduce the final image size
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at the working directory (/app)
COPY requirements.txt .

# Install the Python dependencies specified in requirements.txt
# --no-cache-dir ensures that pip doesn't store the downloaded packages, reducing image size.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code (main.py) into the container
COPY main.py .

# Expose the port the app runs on. This allows AWS App Runner to connect to your application.
EXPOSE 8000

# Define the command to run your app using the Uvicorn server.
# The host 0.0.0.0 makes the container accessible from outside.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

