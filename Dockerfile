FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/your-github-user/ORBELION-ETL-Platform"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl gnupg \
    && curl --fail --silent --show-error --location \
        https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
        --output /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install --no-install-recommends --yes msodbcsql18 unixodbc \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --requirement requirements.txt

COPY --chown=appuser:appuser etl_platform ./etl_platform
COPY --chown=appuser:appuser metadata ./metadata
COPY --chown=appuser:appuser demo ./demo

USER appuser
CMD ["python", "-m", "demo.run_demo"]
