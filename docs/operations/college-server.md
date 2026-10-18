# Running AEGIS on a college server

This guide is for the department or college IT team. When it is done, everyone on campus can open AEGIS at a link like **`https://aegis.yourcollege.edu`**.

## What to ask IT for

| Item | Recommended |
| --- | --- |
| A Linux server or VM | Ubuntu 22.04/24.04 LTS, **4 CPU, 8 GB RAM, 100 GB disk** (more disk for large video evidence) |
| Software | Docker Engine and Docker Compose v2 (https://docs.docker.com/engine/install/ubuntu/) |
| A name | A DNS record such as `aegis.yourcollege.edu` pointing to the server's IP |
| Firewall | Allow inbound TCP **80** and **443**, from the campus network only or from the internet, as policy allows |
| Approval | Your institution's sign-off for processing the evidence you plan to analyse (see `docs/governance/`) |

## Install (about 15 minutes)

On the server:

```bash
git clone https://github.com/kryptonite012/AEGIS-AI-Content-Intelligence-Forensics-System.git aegis
cd aegis
sudo ./scripts/server-setup.sh aegis.yourcollege.edu
```

The script:

- generates strong random secrets in `.env` (readable by root only);
- switches AEGIS to production mode;
- builds and starts every service behind an HTTPS proxy (Caddy);
- asks for the first administrator's email, name, organisation and password.

At the end it prints the link.

**Which HTTPS certificate is used**

- **Public DNS name reachable from the internet:** a free, automatically renewed Let's Encrypt certificate.
- **Campus-only name or an IP address** (for example `sudo ./scripts/server-setup.sh 10.20.30.40`): a certificate from Caddy's internal authority. Browsers warn once. IT can remove the warning by distributing Caddy's root certificate (`docker compose ... exec caddy cat /data/caddy/pki/authorities/local/root.crt`) to campus machines, or by using a certificate issued by the college.

## After installation

1. Open the link and sign in as the administrator.
2. **Administration → Users & roles:** add accounts for investigators, analysts, independent reviewers and auditors.
3. **System Health:** check that every component is operational.
4. Read `docs/governance/human-review-and-appeal-procedure.md` with everyone who will use the system.

## Day-to-day operations (run in the `aegis` folder)

```bash
C="docker compose -f docker-compose.yml -f infrastructure/deployment/docker-compose.server.yml"
$C ps                                   # status of every service
$C logs -f api worker                   # live logs
$C down && $C up -d                     # restart
git pull && $C up -d --build            # update to the latest version (back up first)
$C exec api python -m app.cli verify-audit      # check the audit chain
```

Backups: follow `docs/operations/backup-and-recovery.md`. At minimum, run a nightly `pg_dump` and copy the `evidence` volume.

## Important

- Demo accounts are **not** created on a server: seeding is disabled in production mode.
- No AI-content detector model is bundled. Provenance checks, metadata, forensic views and the reference watermark verifier work immediately. To add learned detectors, see `docs/operations/configuring-detectors.md`.
- Keep `.env` private and back it up securely. It holds the keys that protect sessions and the reference watermark.
