# ADR 0001: Preparation owns serialized setup

## Status

Accepted.

## Context

The API, worker, and scheduler all need an up-to-date database and private object bucket. Letting each process perform setup risks concurrent migrations, partial initialization, and destructive recovery behavior.

## Decision

A dedicated `prepare` Compose service validates configuration, serializes database migration with PostgreSQL coordination, and initializes or reuses the private MinIO bucket. API, worker, and scheduler depend on its successful completion. Preparation is repeatable and never deletes objects, resets data, or downgrades migrations.

## Consequences

Startup failures are visible in the preparation logs and can be retried after the cause is corrected. An incompatible migration requires a forward corrective migration or restore procedure. This implements architecture decision A1 and requirements R1, R2, R3, R4, R9, and R10.
