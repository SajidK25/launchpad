# ADR 0007: Production deployment on the shared Proxmox host

## Status

Accepted for implementation; production rollout and recovery evidence remain pending.

## Context

Launchpad will use the existing shared Ubuntu Proxmox VM without a public IP. Deployment must preserve staging services, use the established outbound Cloudflare Tunnel pattern, and keep application state recoverable. The earlier deployment guide included a dedicated-VM assumption, VM-side source builds, browser-to-R2 upload, and provider setup steps that no longer match confirmed decisions or the implementation.

## Decision

- Run the application as fixed Compose project `launchpad-production` on the shared VM. Treat Docker access as host-level privileged access and retain private LAN/Proxmox recovery access.
- GitHub Actions runs the shared quality gate, builds `linux/amd64` API/web images, publishes private GHCR packages, and automatically deploys the same-run verified `main` release by digest. CI reaches the VM through a Cloudflare Access service token plus SSH with an independently pinned host key. VM source builds and arbitrary image tags are not deployment inputs.
- Keep MinIO for local development and isolated CI. Use a private Cloudflare R2 bucket in production through the same S3-compatible storage boundary. Production configuration fails closed when R2 settings are missing or invalid.
- Route production product/profile uploads through authenticated, byte-limited API endpoints. The API validates the staged object before finalization; browsers do not upload directly to R2. Reads remain private and application-authorized.
- Store runtime secrets in protected service-specific VM configuration. Resend credentials are available to the worker only. Runtime R2 credentials are bucket-scoped; provisioning credentials are not runtime credentials.
- Use maintenance deployments with writers stopped for migrations. Back up the database/configuration before every migration. Restore previous images automatically only when the database schema still matches the previous release; otherwise stop writers and leave maintenance active for explicit recovery. Never automate a destructive schema downgrade.
- Run weekly encrypted PostgreSQL/configuration and media backups with 30-day retention. Media is staged locally from R2 with read-only credentials and a configured disk/byte budget. Keep database/configuration and media repositories and credentials separate. Protect the Restic unlock secret on the VM and keep an independently verified recovery copy outside the VM and the encrypted repository.
- Validate R2 only through a protected workflow using a distinct non-production bucket. Normal pull-request quality checks receive no cloud credentials.

## Consequences

This uses the available VM and avoids inbound router exposure, but a shared Docker host remains a common failure and compromise domain. Staging load can affect production capacity. Weekly media backup leaves a recovery-point gap of up to one week. A successful local quality gate or backup does not prove Cloudflare routing, production R2, VM deployment, or restore readiness. Operators must record isolated restore and provisioned infrastructure evidence before accepting production data.

## References

- [Production deployment guide](../PRODUCTION_DEPLOYMENT_PROXMOX.md)
- [Production recovery guide](../PRODUCTION_RECOVERY.md)
- [Deployment architecture](../../specs/architecture/ARCH-deploy-proxmox-production.md)
