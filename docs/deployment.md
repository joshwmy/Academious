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
