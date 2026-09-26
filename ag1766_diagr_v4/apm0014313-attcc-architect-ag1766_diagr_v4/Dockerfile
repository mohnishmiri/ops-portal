FROM artifact.it.att.com/astra-secure-container-catalog/python:3.13.15 AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build

RUN python -m venv "${VIRTUAL_ENV}"

COPY pyproject.toml README.md ./
COPY src ./src

RUN --mount=type=secret,id=pip_index_url \
    --mount=type=secret,id=pip_trusted_host \
    PIP_INDEX_URL="$(cat /run/secrets/pip_index_url)" \
    PIP_TRUSTED_HOST="$(cat /run/secrets/pip_trusted_host)" \
    pip install --no-cache-dir --upgrade pip \
    && PIP_INDEX_URL="$(cat /run/secrets/pip_index_url)" \
    PIP_TRUSTED_HOST="$(cat /run/secrets/pip_trusted_host)" \
    pip install --no-cache-dir .

FROM artifact.it.att.com/astra-secure-container-catalog/python:3.13.15 AS runtime

# Pin to the Oracle Instant Client version currently served by the permalink
# (instantclient_23_26, BASIC_LITE_README reports 23.26.2.0.0). Oracle only
# publishes a numbered versioned-directory URL for "dbru" base releases (e.g.
# comp-plan-app's 21.11.0.0.0dbru -> .../2111000/...zip); no such numbered
# path is published for this later patch release, so this uses Oracle's
# stable "latest" permalink instead, verified against this exact version's
# published SHA256 so the build fails closed if Oracle rotates the permalink.
ARG ORACLE_IC_VERSION="23.26.2.0.0"
ARG ORACLE_IC_URL="https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip"
ARG ORACLE_IC_SHA256="c36bd3c341cf194fed0a1b71cbd66bfcd37a9d12e1bcfb2c841def272bc9446a"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AWS_OUTPOST_APP_ENV=production \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    ORACLE_IC_HOME="/opt/oracle/instantclient" \
    LD_LIBRARY_PATH="/opt/oracle/instantclient" \
    TNS_ADMIN="/opt/oracle/instantclient/network/admin"

WORKDIR /app

RUN if command -v useradd >/dev/null 2>&1; then \
        groupadd -g 1000 app && useradd -m -u 1000 -g 1000 app; \
    else \
        addgroup -g 1000 app && adduser -D -u 1000 -G app app; \
    fi

# Install Oracle Instant Client and its libaio dependency. The base image is
# WizOS (glibc, apk package manager), not Debian/Ubuntu, so apt-get is absent.
RUN --mount=type=cache,target=/var/cache/apk \
    set -eux; \
    apk add --no-cache ca-certificates libaio; \
    apk add --no-cache --virtual .oracle-ic-deps curl unzip; \
    mkdir -p /opt/oracle /etc/ld.so.conf.d; \
    curl -fsSL "${ORACLE_IC_URL}" -o /tmp/instantclient.zip; \
    echo "${ORACLE_IC_SHA256}  /tmp/instantclient.zip" | sha256sum -c -; \
    unzip -q /tmp/instantclient.zip -d /opt/oracle; \
    ic_dir="$(find /opt/oracle -maxdepth 1 -type d -name 'instantclient_*' | head -n 1)"; \
    mv "$ic_dir" /opt/oracle/instantclient; \
    echo "/opt/oracle/instantclient" > /etc/ld.so.conf.d/oracle-instantclient.conf; \
    ldconfig; \
    rm -f /tmp/instantclient.zip; \
    apk del .oracle-ic-deps

# --- Oracle network/admin config ---
# Do not bake environment-specific TNS aliases into the image.
# If you need TNS aliases, mount `tnsnames.ora` at runtime and/or override `TNS_ADMIN`.
RUN set -eux; \
        mkdir -p /opt/oracle/instantclient/network/admin; \
        printf '%s\n' 'NAMES.DIRECTORY_PATH = (EZCONNECT, TNSNAMES)' > \
            /opt/oracle/instantclient/network/admin/sqlnet.ora

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./src
COPY --chown=app:app alembic.ini ./

RUN mkdir -p /app/evidence \
    && chown app:app /app/evidence

USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live').read()"

ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "uvicorn", "migration_intake.main:get_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
