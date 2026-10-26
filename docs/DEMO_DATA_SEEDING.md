# Demo data seeding

This is a manual operator tool for a disposable local database or the explicitly designated, customer-free demo/staging VM. It creates 20 verified fictional founders, public profiles with local synthetic photos, 20 launched products spread over the seed anchor UTC day and the preceding seven days, six private product-review lifecycle examples, a verified reviewer account, and in-app-only notifications.

It never creates an admin account, sends seed email, runs from deployment, or deletes reviewed/launched products. The seed ledger owns every account/profile/product it creates. Reruns preserve the first UTC date anchor and existing passwords. Cleanup is limited to seed-owned products that have never received a staff review decision.

## Required local fixture media

The CLI validates and loads all fixture images before it connects to PostgreSQL or object storage. The assets must be added at:

- `apps/api/app/operations/demo_seed/assets/avatars/avatar-01.png` through `avatar-20.png`
- `apps/api/app/operations/demo_seed/assets/products/launch-01-logo.png` through `launch-20-logo.png` and matching `launch-NN-screenshot.png`
- `apps/api/app/operations/demo_seed/assets/products/private-{draft,submitted,changes-requested,rejected,approved,scheduled}-{logo,screenshot}.png`

The avatar keys are synthetic and distinct. Every product gets its own fictional logo and screenshot. These assets were generated with OpenAI image generation as a user-authorized substitute for Higgsfield, so no Higgsfield credits were used; no third-party product media or real-person likenesses are included. `assets/manifest.json` records each generation prompt and file. Each file must be a supported PNG and at most 5 MiB. The fixture test validates the complete bundle with the same image decoder and bounds used by storage. Without the complete bundle, `seed` fails before database or storage access.

## Local development

1. From the repository root, start the local dependencies (the one-shot command also starts its declared dependencies):

   ```sh
   docker compose up -d postgres redis minio
   ```

2. Once the fixture bundle is present, run:

   ```sh
   scripts/seed_demo.sh seed
   ```

   The first successful attempt anchors launch dates to the current UTC date. It creates `.launchpad-demo-credentials/local-development.json` with mode `0600`; the directory is mode `0700`. Keep this file private and out of source control. Do not paste its contents into chat, tickets, shell history, or terminal logs.

3. To reconcile after an interrupted run, rerun the same command. The wrapper feeds the private credential file to the one-shot container over stdin; the container emits no credentials on a normal rerun.

4. Sign in using a founder address such as `founder-01@demo.launchpad.example` or the reviewer `reviewer@demo.launchpad.example`. Read the matching password from the private credential file. No default password is used.

5. To delete eligible private examples only:

   ```sh
   scripts/seed_demo.sh cleanup
   ```

   Reviewed products, review history, scheduled products, launched products, launch bookings, and archives are retained. Cleanup does not delete accounts or profiles.

6. Password rotation is a separate explicit command. It writes newly generated credentials to a new private `*-rotation-<UTC timestamp>.json` file and does not overwrite the original manifest:

   ```sh
   scripts/seed_demo.sh rotate-credentials --account-key founder-01
   ```

   Keep the rotation file safe, then update the operator's private credential manifest using an approved secret-handling process.

## Designated VM procedure

The VM may use the production-configured Compose file and R2 credentials only after an operator has confirmed that the database contains no real customer data. The target gate is deliberately fail-closed. Never use this procedure against the live production customer database.

1. Have the VM administrator verify that the VM is designated demo/staging and contains no customer data. Create a root-owned marker whose single line is the agreed target ID (example: `launchpad-demo-staging`):

   ```sh
   printf '%s\n' 'launchpad-demo-staging' | sudo install -o root -g root -m 0644 /dev/stdin /etc/launchpad/demo-seed-target
   sudo stat -c '%U:%G %a %n' /etc/launchpad/demo-seed-target
   ```

   It must report `root:root 644`. The marker is mounted read-only into the one-shot container. Do not create it on a production customer-data VM.

2. Install this repository's `scripts/seed_demo.sh` on the VM and ensure Docker Compose can read `/srv/launchpad/compose.production.yaml`. The production ops service uses the pinned API image, `/etc/launchpad/api.env`, the backend network, and the root-owned marker. It has no published ports, no restart policy, and Docker logging is disabled so credentials cannot be retained in container logs.

3. After the fixture assets have been delivered to the pinned API image, run the explicit target and acknowledgement:

   ```sh
   scripts/seed_demo.sh seed \
     --compose-file /srv/launchpad/compose.production.yaml \
     --target-id launchpad-demo-staging \
     --confirm-no-customer-data \
     --credential-file /srv/launchpad/state/demo-seed-credentials.json
   ```

   The credential file is created once with mode `0600`, owned by the operator running the command. Restrict access to `/srv/launchpad/state`; transfer credentials to stakeholders only through an approved private channel. The wrapper refuses to replace an existing credential file.

4. Reruns must use the same target ID and credential file. Cleanup uses the same explicit target/Compose options, but still retains every reviewed or launched record:

   ```sh
   scripts/seed_demo.sh cleanup \
     --compose-file /srv/launchpad/compose.production.yaml \
     --target-id launchpad-demo-staging \
     --confirm-no-customer-data \
     --credential-file /srv/launchpad/state/demo-seed-credentials.json
   ```

5. Do not run this as part of GitHub Actions, the deployment controller, ordinary Compose startup, or production release. Render Compose config for review without invoking `demo-seed`.

## What the seed demonstrates

- **Founder flow:** verified demo accounts, complete published profiles, and profile photos.
- **Product privacy and review:** draft, pending submission, changes requested, rejected, approved-unscheduled, and approved-scheduled examples created through feature services.
- **Public launches:** 20 distinct products with fictional copy, topics, links, logos, and screenshots across today and seven prior UTC dates.
- **Notifications:** in-app inbox and live-change events; all seed email channels are disabled.
- **Audit and recovery:** a reviewer role granted through audited staff management, a per-target ownership ledger, stable credentials, and fixed date anchors.

The seed is additive beside unrelated records. It aborts when a planned identity collides with an account not proven owned by its ledger. Never manually delete ledger rows or reviewed/launched examples to force a rerun.
