FROM python:3.12-slim-bookworm

WORKDIR /app

# Switch APT to internal mirror (bookworm)
RUN printf "deb https://debian-main.devneeds.ir/ bookworm main contrib non-free non-free-firmware\n\
deb https://debian-main.devneeds.ir/ bookworm-updates main contrib non-free non-free-firmware\n\
deb https://debian-security.devneeds.ir/ bookworm-security main contrib non-free non-free-firmware\n" \
    > /etc/apt/sources.list \
    && apt-get update && apt-get install -y \
        build-essential \
        libpq-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Use internal PyPI mirror
ENV PIP_INDEX_URL=https://pypi.devneeds.ir/simple/

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .