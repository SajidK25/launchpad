FROM golang:1.24.8-bookworm AS minio-build

ARG MINIO_VERSION=github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z

RUN go install -v "${MINIO_VERSION}"

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 minio \
    && useradd --uid 10001 --gid minio --no-create-home --shell /usr/sbin/nologin minio \
    && install -d --owner=minio --group=minio /data

COPY --from=minio-build /go/bin/minio /usr/local/bin/minio

USER minio:minio

ENTRYPOINT ["/usr/local/bin/minio"]
