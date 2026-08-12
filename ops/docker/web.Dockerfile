# syntax=docker/dockerfile:1.7
ARG NODE_IMAGE=node@sha256:d08621e478133b0492bd661ceee5d13a22b8c55297f3dbbb57f1c15d0c214942
FROM ${NODE_IMAGE} AS build
ARG TARGETPLATFORM
WORKDIR /app
RUN test "${TARGETPLATFORM}" = "linux/amd64"
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
ARG TARGETPLATFORM
ARG SOURCE_COMMIT
ARG SOURCE_TREE
ARG BUILD_TIMESTAMP
ENV NODE_ENV=production
WORKDIR /app
RUN test "${TARGETPLATFORM}" = "linux/amd64" \
 && test -n "${SOURCE_COMMIT}" \
 && test -n "${SOURCE_TREE}" \
 && test -n "${BUILD_TIMESTAMP}"
RUN groupadd --system --gid 10001 my-pa \
 && useradd --system --uid 10001 --gid my-pa --home-dir /nonexistent my-pa
COPY --from=build --chown=10001:10001 /app/.next/standalone ./
COPY --from=build --chown=10001:10001 /app/.next/static ./.next/static
COPY --from=build --chown=10001:10001 /app/public ./public
LABEL org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      io.my-pa.repository-tree="${SOURCE_TREE}" \
      org.opencontainers.image.created="${BUILD_TIMESTAMP}" \
      io.my-pa.target-platform="linux/amd64"
USER 10001:10001
EXPOSE 3000
CMD ["node", "server.js"]
