# syntax=docker/dockerfile:1.7
ARG PYTHON_OPERATOR_IMAGE=python@sha256:fbd28bd630d9362e94bf473912fbcb5fcc119bfd06b6091841a13b604581df9a
FROM ${PYTHON_OPERATOR_IMAGE}
ARG TARGETPLATFORM
ARG SOURCE_COMMIT
ARG SOURCE_TREE
ARG BUILD_TIMESTAMP

RUN test "${TARGETPLATFORM}" = "linux/amd64" \
 && test -n "${SOURCE_COMMIT}" \
 && test -n "${SOURCE_TREE}" \
 && test -n "${BUILD_TIMESTAMP}" \
 && python -c 'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
 && git --version \
 && /usr/bin/openssl version \
 && mkdir -p /usr/local/lib/docker/cli-plugins

LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      io.my-pa.repository-tree="${SOURCE_TREE}" \
      org.opencontainers.image.created="${BUILD_TIMESTAMP}" \
      io.my-pa.target-platform="linux/amd64" \
      io.my-pa.operator-runtime="python-3.12"

USER 65534:65534
CMD ["python", "--version"]
