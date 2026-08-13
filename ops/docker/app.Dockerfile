# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python@sha256:c00fc7b44d844b6da22861ec24af43968a5200eac4ec607b4725d585165d6b49
FROM ${PYTHON_IMAGE} AS runtime
ARG TARGETPLATFORM
ARG SOURCE_COMMIT
ARG SOURCE_TREE
ARG BUILD_TIMESTAMP
ARG PYTHON_RUNTIME_LOCK_SHA256

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/my-pa/venv/bin:$PATH
WORKDIR /opt/my-pa

RUN test "${TARGETPLATFORM}" = "linux/amd64" \
 && test -n "${SOURCE_COMMIT}" \
 && test -n "${SOURCE_TREE}" \
 && test -n "${BUILD_TIMESTAMP}" \
 && test -n "${PYTHON_RUNTIME_LOCK_SHA256}"
RUN python -m venv /opt/my-pa/venv
COPY pyproject.toml README.md ./
COPY ops/docker/python-runtime.lock ./ops/docker/python-runtime.lock
RUN printf '%s  %s\n' "${PYTHON_RUNTIME_LOCK_SHA256}" ops/docker/python-runtime.lock \
 | sha256sum --check --strict -
COPY src ./src
COPY apps ./apps
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir --disable-pip-version-check \
      --constraint ops/docker/python-runtime.lock . \
 && pip check

RUN addgroup --system --gid 10001 my-pa \
 && adduser --system --uid 10001 --ingroup my-pa --home /nonexistent --no-create-home my-pa
LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      io.my-pa.repository-tree="${SOURCE_TREE}" \
      org.opencontainers.image.created="${BUILD_TIMESTAMP}" \
      io.my-pa.target-platform="linux/amd64" \
      io.my-pa.python-runtime-lock-sha256="${PYTHON_RUNTIME_LOCK_SHA256}"
USER 10001:10001
CMD ["python", "apps/gateway.py", "--help"]
