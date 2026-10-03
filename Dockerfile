FROM python:3.13-slim

# System-level dependencies install karein taaki Playwright kabhi crash na ho
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libexpat1 libfontconfig1 libgbm1 \
    libgdk-pixbuf-2.0-0 libgtk-3-0 libpango-1.0-0 \
    libpangocairo-1.0-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 \
    libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 \
    libxrender1 libxtst6 xdg-utils curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright aur Chromium browser install karein
RUN playwright install chromium

COPY . .

CMD ["python", "loot_listener.py"]