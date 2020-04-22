FROM python:3-slim

# -----------------------------------------------------------------------------

ARG BUILD_DATE
ARG BUILD_VERSION

LABEL \
  version="${BUILD_VERSION}" \
  maintainer="Alexander Sytar <sytar.alex@gmail.com>" \
  org.label-schema.build-date=${BUILD_DATE} \
  org.opencontainers.image.created=${BUILD_DATE} \
  org.opencontainers.image.authors="Alexander Sytar <sytar.alex@gmail.com>" \
  org.opencontainers.image.url="https://github.com" \
  org.opencontainers.image.version="${BUILD_VERSION}" \
  org.opencontainers.image.licenses="MIT" \
  org.opencontainers.image.title="zabbix2kafka" \
  org.opencontainers.image.description="Export Zabbix metrics to kafka transport"


# -----------------------------------------------------------------------------


WORKDIR /app

COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
  && rm -Rf /root/.cache \
  && find / -type d -name __pycache__ -exec rm -r {} \+

ENV PYTHONUNBUFFERED 1

COPY main.py .

ENTRYPOINT ["python", "main.py"]

HEALTHCHECK \
  --interval=5s \
  --timeout=2s \
  --retries=12 \
  CMD ps ax | grep -v grep | grep -c main.py || exit 1