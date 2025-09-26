# Use an official, specific Python runtime as a parent image for reproducibility.
FROM python:3.9-slim

# Set the working directory inside the container.
WORKDIR /app

# Install system dependencies required for Google Chrome and its driver.
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    gnupg \
    # Add Google’s signing key
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    # Add Google Chrome repository
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    # Install Chrome
    && apt-get install -y google-chrome-stable \
    # Cleanup to keep image small
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
