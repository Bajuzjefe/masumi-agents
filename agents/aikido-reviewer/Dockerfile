FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Aikido CLI binary for auto-scan mode.
RUN curl -fsSL \
    https://github.com/Bajuzjefe/Aikido-Security-Analysis-Platform/releases/download/v0.3.1/aikido-x86_64-unknown-linux-gnu.tar.gz \
    | tar xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/aikido

COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8011

CMD ["python", "main.py"]
