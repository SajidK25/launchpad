# ADR 0003: Private S3-compatible object storage

## Status

Accepted.

## Context

Product and media objects must never become public by default. Local development needs an S3-compatible service without a cloud account, while staging and production will need a managed provider. Frontend assets have a different lifecycle from private objects.

## Decision

Use private MinIO storage locally behind an S3-compatible client boundary. The same boundary can target Cloudflare R2 in future staging and production work. The web container keeps compiled frontend assets; MinIO/R2 are not used for those assets in this foundation.

## Consequences

Preparation creates or reuses a private bucket and application access uses separate runtime credentials. R2 configuration and credentials are deferred. This implements the object-storage and frontend-asset choices and requirements R8, R9, and N3.
