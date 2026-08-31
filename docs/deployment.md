# Deployment

Approved target: a single VPS running Docker Compose. No Redis, no Celery, no
Kubernetes, no standalone vector database.

The provider is **netcup**, not Hetzner as originally specified. Hetzner was the
Phase 0 choice and remains a fine one; every 8 GB plan was simply out of stock
across Falkenstein, Helsinki and Nuremberg, on both x86 and Arm, at the point of
purchase. Nothing in the repository is provider-specific - the stack is Docker
Compose on Ubuntu - so this is a purchasing fact, not an architectural one.

> **This target is not what is running today.** Production testing currently
> goes Vercel -> Cloudflare quick tunnel -> a development PC -> Caddy -> the
> application, which means the backend is available only while that machine is,
> and the tunnel hostname is ephemeral. Everything below describes the intended
> deployment. The gap, and everything blocked behind it, is
> [DEPLOY-001](backlog.md#deploy-001).

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

`docker-compose.yml` runs `db`, `api` and `worker`, and is the file used for local
development. `docker-compose.prod.yml` overlays it with Caddy and the production
restart policies. The frontend is not served from this box: it is a static Vite
build on Vercel, so Caddy fronts the API alone.

## Sizing

| Stage | Machine | Notes |
|---|---|---|
| Phase 1-2 | netcup VPS 1000 G12 (4 vCore / 8 GB DDR5 ECC / 256 GB NVMe) | ~EUR 8/month, hourly billing, no minimum term |
| ~1,000 users | next tariff up, or an equivalent 16 GB plan | vertical, a few minutes of downtime |
| ~10,000 users | dedicated box (64 GB) for PostgreSQL, app nodes behind a load balancer | |

8 GB is the floor, and it is set by the corpus rather than by traffic. Steady
state is Postgres plus the API at roughly 2 GB; the nightly embed adds 1.0-1.5 GB
of resident torch on top. A 4 GB machine survives that only with swap, and it
leaves no page cache for a corpus that outgrows RAM within the first year.

Disk is sized the same way and is the reason the smaller tariffs were rejected:
14 GB/year of metadata, 4.1 GB/year of embeddings, indexes that often run
50-100% of table size, plus ~4 GB for an image carrying torch - of which two
copies exist during a deploy.

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

## The production overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The overlay adds `caddy` and pins it to `172.28.0.10` on a dedicated `edge`
network. That address is not decoration: `--forwarded-allow-ips` names one exact
host, so "the proxy" cannot be satisfied by any other container that happens to
come up on the same network (SEC-004).

What the base file already does, and why:

* **Both published ports bind `127.0.0.1`**, never `0.0.0.0`. This matters more
  off Hetzner than on it. Hetzner's cloud firewall sits outside the machine and
  would have caught a bare `5432:5432`; netcup has no such layer, and Docker
  writes its iptables rules *ahead* of ufw's chain, so a host firewall does not
  save you either. The bind is the control.
* **`POSTGRES_PASSWORD` has no default.** Compose refuses to start without it
  rather than falling back to a value committed to the repository.

`Caddyfile` implements the three controls `security.md` assigns to the deployment
layer: TLS and HSTS (SEC-005), transport and body size limits (SEC-005), and a
404 on `/metrics/*` and `/health/db` (SEC-003). Plain `/health` stays public for
uptime checks. Read the restricted endpoints from the box itself:

```bash
curl -s 127.0.0.1:8000/metrics/ingestion
```

### Host firewall

There is no cloud firewall to fall back on. On the server:

```bash
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### Production settings

`.env` on the server differs from a development one in four values, listed in
`.env.example`. `ACADEMIOUS_TRUSTED_PROXY_COUNT=1` is the one that is silently
wrong at its default: at 0 every request appears to originate from Caddy, so all
clients share a single rate-limit bucket.

### First deploy

1. DNS: `api.academious.org` A record at the VPS address. Caddy cannot issue a
   certificate before this resolves.
2. `.env` on the server, with a generated `POSTGRES_PASSWORD` and the production
   values above.
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
4. `docker compose run --rm api alembic upgrade head`
5. `curl https://api.academious.org/health`
