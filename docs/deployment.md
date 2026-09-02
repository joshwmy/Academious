# Deployment

Approved target: a single VPS running Docker Compose. No Redis, no Celery, no
Kubernetes, no standalone vector database.

The provider is **netcup**, not Hetzner as originally specified. Hetzner was the
Phase 0 choice and remains a fine one; every 8 GB plan was simply out of stock
across Falkenstein, Helsinki and Nuremberg, on both x86 and Arm, at the point of
purchase. Nothing in the repository is provider-specific - the stack is Docker
Compose on Debian 13 - so this is a purchasing fact, not an architectural one.

> **The backend runs on this target as of 2026-09-01.** `api.academious.org`
> resolves to the VPS, Caddy holds a Let's Encrypt certificate, and the corpus
> is 33,169 papers across arXiv, bioRxiv/medRxiv and Europe PMC. The Cloudflare
> tunnel off a development PC is retired.
>
> Two things are still true and worth stating plainly. **The frontend has not
> been repointed**: the Vercel build still names the tunnel hostname, so the
> deployed site calls a backend that no longer answers until
> `VITE_API_BASE_URL` changes and it is rebuilt (DEPLOY-002). The schedule from
> [`deploy/crontab`](../deploy/crontab) is installed, so harvesting and
> embedding now run unattended. There are also no backups (DEPLOY-006), which mattered less when the
> corpus was minutes of re-harvesting and matters more now that it is hours.

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

## Provisioning the host

The machine is a netcup VPS 1000 G12 running **Debian 13 (trixie) minimal**,
`159.195.245.28` / `2a0a:4cc0:61:185c:14b4:24ff:feae:210`. Minimal means no
editor, no firewall, no Docker: everything below is a first-boot step, not a
tuning pass.

### SSH: keys only

netcup mails the initial root password in plaintext, so it is compromised on
arrival and is rotated before anything else. Password authentication is then
turned off entirely.

Put the workstation's public key on the box first, and **prove key login works
before disabling passwords** - a broken sshd config plus a closed session means
recovering through the provider's VNC console.

```bash
# /etc/ssh/sshd_config.d/99-hardening.conf
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
```

A drop-in rather than an edit to `sshd_config`: Debian includes the directory
from the top of the main file, so the drop-in wins, and a package upgrade cannot
quietly revert it.

```bash
sshd -t && systemctl restart ssh    # validate before restarting, always
```

Debian 13 socket-activates SSH; if the restart errors, the unit is `ssh.socket`.

Verify from a *second* terminal, with the first still open:

```bash
ssh -o PreferredAuthentications=password root@<host>   # must fail: publickey
```

That failure is the success condition.

### Firewall

```bash
apt update && apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw enable
```

Repeating the warning from "The production overlay" below, because it is the
control people assume they have and do not: **ufw does not protect published
Docker ports.** Docker inserts its own iptables rules ahead of ufw's chain. The
`127.0.0.1` binds in `docker-compose.yml` are what keeps Postgres and uvicorn
off the internet, and there is no cloud firewall on netcup behind which to hide
a mistake.

### Docker Engine

From Docker's own repository, not Debian's `docker.io` package - the compose
plugin and current engine are only there.

```bash
apt install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

If `apt update` 404s on the `trixie` suite, Docker has not published for it yet;
substitute `bookworm` in the `sources.list.d` entry. Verify:

```bash
docker compose version
```

### Clock and cron windows

`docs/deployment.md` schedules harvests against NCBI's off-peak window, which is
stated in **US Eastern**, while a fresh VPS runs UTC. Either set the host clock
to a zone you can reason about, or convert the window and leave the host on UTC -
but do it deliberately, because a job that drifts into NCBI's peak hours is
answered with an IP ban rather than a warning.

```bash
timedatectl set-timezone Etc/UTC
timedatectl                      # confirm, and confirm NTP is synchronised
```

### Unattended security updates

The box runs unattended between deploys and is reachable on 22, 80 and 443.

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

Kernel updates still need a reboot; `/var/run/reboot-required` says when one is
pending.

### Application directory

```bash
mkdir -p /srv/academious
git clone <repository> /srv/academious
cd /srv/academious
```

`/srv` because the cron entries in "Scheduling" below hard-code
`cd /srv/academious`. Changing the location means changing them too.

Then write `.env` from `.env.example`, with the four production values listed
under "Production settings" and a generated `POSTGRES_PASSWORD`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
chmod 600 .env
```

`.env` holds the database password and every API key, so it is `600` and it is
never committed - `.gitignore` already excludes it.

### Pinning the compose files

Every command on the server needs both files. A bare `docker compose ...` reads
`docker-compose.yml` alone, which has no `caddy` service, no restart policies and
none of the proxy pinning - so the mistake does not error, it silently runs the
development topology. Set this once, in the server's `.env`:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```

`docker compose` reads `COMPOSE_FILE` from `.env` in the project directory, so
plain `docker compose up -d`, `logs`, `ps` and `run` all pick up the overlay
afterwards, including the cron entries under "Scheduling" below. The variable is
also passed into the containers, where it is inert.

Development machines leave it unset and get the base file, which is the point.

### Still root-only

Everything above runs as root over SSH, which is what the CI/CD step in this
document assumes. A dedicated deploy user in the `docker` group is the better
end state, but note that membership of `docker` is equivalent to root on the
host, so it buys less isolation than it appears to.

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

The schedule lives in [`deploy/crontab`](../deploy/crontab) rather than in this
document, so that what runs on the box is a file under version control instead
of a snippet somebody pasted once.

```bash
timedatectl                       # must report UTC before this means anything
mkdir -p /var/log/academious
crontab /srv/academious/deploy/crontab
crontab -l
```

**Check the clock first.** cron fires on the host's *local* time, not UTC, and a
VPS comes up in its datacentre's zone — netcup's German images on UTC+2. The
schedule then runs at the wrong hour without any error: on UTC+2 the 02:30 entry
lands at 20:30 US Eastern, half an hour outside the window NCBI enforces with IP
bans. `journalctl` prints local time while `date -u` prints UTC, so comparing
the two is the quickest way to notice.

| Entry | When (UTC) | Why then |
|---|---|---|
| `harvest --source all` | hourly, `:10` | Incremental and cursor-resumable; a missed run costs freshness, not data |
| `embed` | every 30 min | Drains whatever the harvest added, ~1 paper/second |
| `link-publications` | 02:30 | Off-peak; the preprint→published map |
| `retractions` | 03:45 | Off-peak; ~66 MB download |

Three properties of that file are load-bearing, and all three are easy to lose
if the entries are retyped by hand.

**`flock -n` on every entry.** It skips a run whose predecessor is still going
rather than queuing it. The embed job routinely runs for hours against a
30-minute schedule, so without the lock cron stacks containers until the box
runs out of memory. Not a risk — a certainty, on the first large backlog.

**An `embed` entry at all.** This is the one whose absence is invisible. A
harvest that adds papers nothing embeds still reports success, the feed still
shows the new papers, and only semantic search quietly answers from a shrinking
share of the corpus. On 2026-09-01 a single OpenAlex run added 42,609 papers and
search coverage fell from 30% to 13% with nothing anywhere reporting a failure.
Scheduling harvest without scheduling embed makes that permanent.

**The off-peak window is in UTC.** NCBI asks that large jobs run at weekends or
21:00-05:00 US Eastern and enforces it with IP bans, while the host runs UTC.
That window is 01:00-09:00 UTC under US daylight time and 02:00-10:00 under
standard time; the nightly entries at 02:30 and 03:45 are inside both. Moving
them means redoing that conversion. The hourly harvest runs outside the window
by design and is safe only because no NCBI connector exists yet —
[SRC-001](backlog.md#src-001) has to revisit this when PubMed lands.

### Watching it

```bash
tail -f /var/log/academious/embed.log
grep -c '"level": "error"' /var/log/academious/*.log
```

Nothing rotates these logs yet. `/etc/logrotate.d/academious`:

```
/var/log/academious/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

The corpus is also queryable directly, which is the check that matters most —
whether embedding is keeping up with ingestion:

```bash
docker compose exec db psql -U academious -d academious   -c "select (select count(*) from paper) as papers,
             (select count(*) from paper_embedding) as embedded"
```

A gap that grows run over run means the schedule is not draining the queue and
search coverage is falling.

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
curl -s -H 'Host: api.academious.org' 127.0.0.1:8000/metrics/ingestion
```

The `Host` header is not decoration. `ACADEMIOUS_ALLOWED_HOSTS` names the
public hostname, so a request addressed to `127.0.0.1` is answered with
`Invalid host header` before it reaches the route - the endpoint looks broken
when it is in fact working exactly as configured.

### Host firewall

Configured during provisioning - see "Firewall" above. There is no cloud
firewall to fall back on, and ufw does not cover published Docker ports, so the
`127.0.0.1` binds in `docker-compose.yml` remain the control that matters.

### Production settings

`.env` on the server differs from a development one in four values, listed in
`.env.example`. `ACADEMIOUS_TRUSTED_PROXY_COUNT=1` is the one that is silently
wrong at its default: at 0 every request appears to originate from Caddy, so all
clients share a single rate-limit bucket.

### First deploy

The host must be provisioned first - see "Provisioning the host" above.

1. **DNS.** `api.academious.org` A record at `159.195.245.28`, AAAA at
   `2a0a:4cc0:61:185c:14b4:24ff:feae:210`. DNS is hosted at Porkbun; the apex
   `academious.org` is a separate A record pointing at Vercel, and the two are
   easy to confuse because the frontend's apex record and a stale Vercel record
   for `api` carry the same address. Confirm the name resolves to the VPS *and
   nothing else* before starting Caddy:

   ```bash
   nslookup api.academious.org 1.1.1.1
   ```

   Two A records on `api` means round-robin, so half of Let's Encrypt's
   validation requests reach the wrong host. Issuance failures are rate-limited
   at 5/hour per hostname, so this is checked, not assumed.

2. **`.env` on the server**, with a generated `POSTGRES_PASSWORD`, the
   production values above, and `COMPOSE_FILE` set as described under "Pinning
   the compose files".
3. **Database first, then migrations, then the rest.** The order is not
   cosmetic: the API answers requests as soon as it starts, and anything that
   touches a table before `alembic` has created it fails on a missing relation.

   ```bash
   docker compose up -d db
   docker compose run --rm api alembic upgrade head
   docker compose up -d
   ```

4. `curl https://api.academious.org/health` - expect `{"status":"ok"}`.
5. Watch the certificate being issued, once:

   ```bash
   docker compose logs caddy | grep -i "certificate obtained"
   ```

6. First harvest, by hand rather than waiting for cron:

   ```bash
   docker compose run --rm worker python -m academious.workers harvest --source all
   ```

7. **Embed the corpus.** A harvested corpus is not yet a searchable one:
   `/search` encodes the query at request time and ranks against
   `paper_embedding`, so until this runs the API answers every search with
   nothing while looking entirely healthy.

   ```bash
   docker compose run --rm worker python -m academious.workers embed --pending
   docker compose run --rm worker python -m academious.workers embed
   ```

   `--pending` reports the backlog without loading the model, which makes it a
   cheap check that the queue is what you expect before committing to the work.
   The first real run downloads ~440 MB of SPECTER2 weights into the
   `modelcache` volume; later runs reuse it.

   **One pass is not the whole corpus.** `MAX_PENDING_SCAN` in
   `embeddings/service.py` caps each enqueue at 10,000 papers, so a corpus
   larger than that needs the command run repeatedly - and the failure mode is
   silent, because the papers that were embedded search perfectly well while
   the rest are simply absent from every result. Repeat until `--pending`
   reports nothing:

   ```bash
   until [ "$(docker compose run --rm worker python -m academious.workers embed        --pending 2>/dev/null | tr -d "
" | tail -1)" = "0" ]; do
     docker compose run --rm worker python -m academious.workers embed
   done
   ```

   `--pending` prints a bare count, not JSON. A loop that greps for a JSON key
   never satisfies its condition and spins re-running a no-op embed forever
   once the backlog clears - which looks like progress in `ps` and is not.

   At the measured 1.0-1.4 papers/second (see
   [performance.md](performance.md) §2) a 33k corpus is 7-9 hours, so run it
   detached - `docker compose run -d --rm worker ...` - rather than from a
   session that ends when the laptop sleeps.

8. **Derive the subject fields.** Migration `0004` adds `paper.fields` empty,
   because the mapping it holds lives in Python and a data migration would
   freeze one version of it into history. Until the backfill runs, every field
   filter matches nothing and `GET /fields` reports every field at zero - which
   looks like an empty corpus rather than a missing step.

   ```bash
   docker compose run --rm worker python scripts/backfill_fields.py           # report
   docker compose run --rm worker python scripts/backfill_fields.py --apply   # write
   ```

   The script is in the image because the `Dockerfile` copies `scripts/`. It
   was not, on the release that first shipped this migration, and the failure
   is worth knowing: `alembic upgrade head` succeeded, the API came up serving
   a field filter, and the backfill died on `can't open file`. Between those
   two moments every field matched nothing while `/fields` reported the whole
   vocabulary at zero - a live filter over a column no code had populated. If
   an image ever lacks it again, mount it rather than rebuilding:

   ```bash
   docker compose run --rm -v /srv/academious/scripts:/app/scripts worker      python scripts/backfill_fields.py --apply
   ```

   It is a pure re-derivation from stored topics: no network, no model, and
   idempotent, so a second run writes nothing. Run it again after any change to
   `ingest/taxonomy.py` - ordinary ingestion repairs a paper only when a source
   next describes it, and nothing describes an old paper on a schedule.

   The dry run's summary is the thing to read, not just its exit code: it
   reports the share of papers carrying no field, and lists category labels that
   mapped to nothing. A label appearing there is a connector emitting vocabulary
   the mapping has not met.

Then confirm the deployment-layer controls actually hold, from the server:

```bash
curl -s -o /dev/null -w "%{http_code}
" https://api.academious.org/metrics/ingestion  # 404
curl -s -o /dev/null -w "%{http_code}
" https://api.academious.org/health/db          # 404
curl -sI https://api.academious.org/health | grep -iE 'strict-transport|^server'        # HSTS, no Server
```

and that Postgres is not listening publicly, from somewhere else entirely:

```bash
nc -vz <vps address> 5432    # must fail
```

Then repoint the frontend: the Vercel project is still built against the
Cloudflare tunnel hostname, so its API base URL has to become
`https://api.academious.org` and the site has to be rebuilt. Until that happens
the deployed site calls a tunnel that no longer exists (DEPLOY-002).
