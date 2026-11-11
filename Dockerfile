# Single-host production reference: independent web API and background worker.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /srv/rizzler
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rizzler && useradd --uid 10001 --gid 10001 -m rizzler
COPY pyproject.toml README.md requirements-identity.txt ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[voice,work]" -r requirements-identity.txt \
    && mkdir -p /var/lib/rizzler /home/rizzler/.cache \
    && chown -R rizzler:rizzler /var/lib/rizzler /home/rizzler/.cache
USER rizzler
ENV RIZZLER_HOST=0.0.0.0 RIZZLER_PORT=8000
EXPOSE 8000
CMD ["python", "-m", "rizzler"]
