FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY pyproject.toml README.md ./
COPY bookspine ./bookspine
RUN pip install --no-cache-dir .

RUN useradd --create-home bookspine \
    && mkdir -p /data \
    && chown -R bookspine:bookspine /data /app
USER bookspine

ENV BOOKSPINE_DATA=/data
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://localhost:8080/healthz', timeout=2)" || exit 1

CMD ["bookspine", "serve", "--host", "0.0.0.0", "--port", "8080"]
