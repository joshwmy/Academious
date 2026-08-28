# Deployment

Approved target: a single Hetzner VPS running Docker Compose. No Redis, no
Celery, no Kubernetes, no standalone vector database.

## Topology

```
                 Caddy (TLS, reverse proxy)
                   |
      +------------+------------+
      |                         |
  frontend (static)      api (FastAPI/uvicorn)
                               |
                        PostgreSQL 17 + pgvector
                               |
                        worker (cron-driven)
```

`docker-compose.yml` in the repository runs `db`, `api` and `worker`. The reverse
proxy and frontend arrive in Phase 2, when there is a frontend to serve.

## Sizing

| Stage | Machine | Notes |
|---|---|---|
| Phase 1-2 | Hetzner CX32 (4 vCPU / 8 GB / 80 GB) | ~EUR 8/month |
| ~1,000 users | CPX41 | vertical, a few minutes of downtime |
| ~10,000 users | dedicated AX41/AX52 (64 GB) for PostgreSQL, app nodes behind a load balancer | |

Corpus growth is roughly 14 GB/year of metadata plus 2.7 GB/year of embeddings
once Phase 3 lands. Managed free tiers (Neon 0.5 GB, Supabase 500 MB) are about
30x too small, which is why PostgreSQL is self-managed.

## Migrations

```bash
alembic upgrade head          # forward
alembic downgrade -1          # back one revision
alembic revision --autogenerate -m "description"
```

`migrations/env.py` always takes the database URL from settings, never from
`alembic.ini`, so there is no second place for a connection string to drift.

Every migration must be reversible. `0001` creates `pg_trgm`, which fuzzy
deduplication requires - a database without it will fail dedup at runtime, not at
startup, so the extension is created in the migration rather than assumed.

## Scheduling

Cron on the host, or systemd timers. Off-peak windows matter: NCBI asks that
large jobs run at weekends or 21:00-05:00 US Eastern, and enforces it with IP
bans.

```cron
# Harvest every source, hourly, at ten past
10 * * * *  cd /srv/academious && docker compose run --rm worker \
              python -m academious.workers harvest --source all

# Preprint publication map, nightly
30 2 * * *  cd /srv/academious && docker compose run --rm worker \
              python -m academious.workers link-publications

# Retraction Watch, nightly (66 MB download)
45 3 * * *  cd /srv/academious && docker compose run --rm worker \
              python -m academious.workers retractions
```

## Backups: encrypted and off-machine

A backup that lives on the VPS disk is not a backup. This is a design obligation
from Phase 0 and must be in place before any real user data exists.

**Requirements**

1. **Off-machine.** Object storage with no egress fees - Backblaze B2 or
   Cloudflare R2.
2. **Encrypted before it leaves the host.** Age or GPG with a public key; the
   private key is never stored on the server that makes the backups.
3. **Point-in-time recovery**, not just nightly dumps. WAL archiving via
   `pgBackRest` or `wal-g`, so recovery granularity is minutes rather than a day.
4. **Retention**: 7 daily, 4 weekly, 12 monthly.
5. **Restore drills.** A backup nobody has restored is a hypothesis. Restore into
   a scratch database quarterly and record the result; that drill is an exit
   criterion for Phase 6.
6. **Monitored.** A backup that silently stopped is worse than none, because it
   buys false confidence. Alert when the newest object in the bucket is older
   than 26 hours.

**Shape**

```
pgBackRest (WAL + incremental)  ->  age -r <public key>  ->  B2/R2 bucket
                                                             lifecycle rules
                                                             enforce retention
```

The private key lives in a password manager and in one offline copy. Losing it
means losing every backup, so it is treated with the same care as the domain
registrar credentials.

**What is not backed up:** `source_record` payloads could be re-fetched from the
sources, but re-harvesting a full corpus costs days of rate-limited requests.
They are backed up. Nothing is excluded in Phase 1.

## Secrets

Environment only, via `.env`, never committed. `.env.example` documents every
variable with placeholder values. `.gitignore` excludes `.env`.

Secrets in play by Phase 3: OpenAlex API key, NCBI API key, contact email, the
database password, the backup encryption public key, and the SMTP or Resend key.

## CI/CD

GitHub Actions builds the image and pushes to GHCR; deployment is
`docker compose pull && docker compose up -d` over SSH. Migrations run as a
separate step before the new image starts serving.
