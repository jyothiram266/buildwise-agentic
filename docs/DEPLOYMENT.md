# Deployment — step by step

Three routes, easiest first. All three run the same image; the only difference is
who supplies Postgres.

Throughout: **no API key is required.** The system defaults to a deterministic
offline provider so it runs and demos completely without one.

---

## Route 1 — local, with Docker (start here)

### 1. Prerequisites

- Docker Desktop 4.x or Docker Engine 24+ with Compose v2
- 4 GB free RAM, 2 GB disk
- Ports free: 3000, 5432, 6379, 8000, 8100

Check:

```bash
docker --version
docker compose version
```

### 2. Get the code and configure

```bash
cd buildwise-agentic
cp .env.example .env
```

Nothing in `.env` needs editing to run. Every value has a working default.

### 3. Start the containers

```bash
make up
```

Equivalent to `docker compose up -d --build`. First run builds the image and takes
2–4 minutes. Watch it come up:

```bash
docker compose ps
```

Wait until `postgres` and `redis` show `healthy`. The `api` container will restart
once or twice while Postgres finishes initialising — that is expected.

### 4. Populate the database

```bash
make bootstrap
```

This runs, in order, and is safe to re-run:

1. schema and migrations
2. generate deterministic seed data (fixed seed, so everyone gets identical data)
3. load it — 4 projects, 9 towers, 404 units, 60 customers, 780 documents, 80 tickets, 50 leads
4. build the knowledge corpus **from that seed data**, so the documents and the
   systems of record cannot disagree
5. chunk, embed and index — 26 documents

Expect ~60 seconds and a summary table at the end.

### 5. Confirm the demo is ready

```bash
make selfcheck
```

Checks connectivity, prompt and policy versions, row counts, the demo personas, and
the deliberately seeded conditions (Aurora has no 1BHK, Tower B's revision is
approved, Tower E's is not, injection probes are present, the price list is stale).
Each failure prints the command that fixes it.

### 6. Open it

| What | Where |
|---|---|
| Console | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| Systems of record | http://localhost:8100/health |

The **"Acting as"** selector in the top right is the demo. Switching identity
changes what the API returns, not what the UI hides.

### 7. Try it

As **Priya Sharma (prospective buyer)**:
> Do you have any 2BHK under 85 lakhs in Whitefield?

As the same person:
> Any 1BHK available at Aurora Heights?

As **Rakesh Menon (customer)**:
> Why has my possession date moved again? I want a refund if this continues.

Then switch to **Kavitha (manager)** → **Approvals** and **Audit**, paste the case
id from the reply, and read the decision path.

[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) walks all eight journeys with what to point at.

### Using a real model

```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
docker compose up -d --force-recreate api
```

Everything else is unchanged. The provider is the only thing that moves.

### Stopping

```bash
make down       # stop, keep the data
make down -v    # stop and delete the database volume
```

---

## Windows / PowerShell

`make` is not present on Windows. It is only a shortcut runner, so every target has
a direct equivalent:

| Instead of | Run |
|---|---|
| `make up` | `docker compose up -d --build` |
| `make down` | `docker compose down` |
| `make logs` | `docker compose logs -f api` |
| `make bootstrap` | `docker compose exec api python scripts/bootstrap.py` |
| `make selfcheck` | `docker compose exec api python scripts/selfcheck.py` |
| `make audit` | `docker compose exec api python scripts/spec_audit.py` |
| `make test-unit` | `docker compose exec api pytest tests/unit -q` |
| `make test` | `docker compose exec api pytest tests -q` |
| `make eval` | `docker compose exec api python -m eval.run` |
| `make ingest` | `docker compose exec api python -m retrieval.ingest --all` |
| `make web-build` | `docker compose run --rm web sh -c "npm install && npm run build"` |

Test and lint tooling is installed in the image by default, so none of this needs a
local Python setup. Build with `--build-arg INSTALL_DEV=false` for a lean production
image.

`scripts/dev_up.sh` is bash and will not run in PowerShell — the first three
commands in the table are exactly what it does.

---

## Route 2 — hosted on Render (public URL, free tier works)

`render.yaml` is a blueprint, so most of this is clicking. One web service, one
managed Postgres. The API serves the compiled frontend on the same origin and runs
the mock systems of record on loopback inside the same container.

### 1. Push to GitHub

```powershell
cd <your project folder>
git init
git add .
git commit -m "BuildWise agentic support system"
git branch -M main
git remote add origin https://github.com/<you>/buildwise-agentic.git
git push -u origin main
```

The repository can be private; Render authorises through GitHub.

### 2. Create the blueprint

1. Sign in at https://dashboard.render.com
2. **New** → **Blueprint**
3. Connect the repository. Render reads `render.yaml` and proposes:
   - `buildwise-db` — managed Postgres (free)
   - `buildwise` — the web service (free)
4. **Apply**

The first build takes 6–10 minutes: it installs Python dependencies, then runs
`npm install && npm run build` for the frontend inside the image.

### 3. Wait for the first boot to finish

Watch the service **Logs** tab. On first boot the container seeds itself, because
free instances have no shell and the database cannot be populated by hand:

```
→ BuildWise starting (api port 10000, connectors on loopback 8100)
→ waiting for connectors ok
→ bootstrap (skipped if already populated)
   ... 404 units, 26 corpus documents, 146 chunks ...
→ serving
```

That takes about 60 seconds. Every later restart prints `already populated — nothing
to do` and starts immediately.

### 4. Open the URL

`https://buildwise-<hash>.onrender.com` — the console and the API share the origin,
so nothing else needs configuring. Check `/health` first: it reports `ok`, the LLM
provider, and the dense retrieval mode.

### What to know before sharing the link

**Anyone with the URL can act as any persona.** `render.yaml` sets `APP_ENV=dev`
deliberately: in prod mode the `X-Actor-Id` header and the demo token endpoint are
both refused, which is correct for a real system and would break the role switcher
that is the entire demo. Every record is synthetic seed data, so this is a reasonable
trade for a demo — but do not put real customer data behind it without real
authentication.

**Free instances sleep after 15 minutes idle.** The first request afterwards takes
~30 seconds while the container wakes. Before a live demo, open the URL a minute
early. Free Postgres also expires after 90 days.

**No pgvector on the free database tier.** Handled: the app detects the extension at
boot and scores cosine similarity in Python over ACL-filtered rows instead. Same
answers, slower ranking, access control unchanged — it stays in SQL either way.
`/health` shows `dense_mode`.

### Using a real model

Add the key in the service's **Environment** tab and redeploy:

```
LLM_PROVIDER      anthropic
ANTHROPIC_API_KEY sk-ant-...
```

Nothing else changes. The wording becomes natural; the tiering, access control,
citations and audit trail are identical.

### If the deploy fails

| Symptom | Cause |
|---|---|
| Build fails in the `web` stage | A TypeScript error. Reproduce locally with `docker compose run --rm web sh -c "npm install && npm run build"` |
| Health check never passes | Read the logs. If bootstrap is looping, `DATABASE_URL` is not attached — check the blueprint linked the database |
| Site loads, "API unreachable" | The frontend was not compiled into the image. Confirm `dockerBuildArgs: BUILD_WEB: "true"` survived in `render.yaml` |
| Every answer says information is unavailable | Bootstrap did not complete. The logs will show where; a manual redeploy re-runs it |

### Railway / Fly.io / Heroku

The same shape works anywhere that runs a Dockerfile. Provide `DATABASE_URL`,
point `MOCK_CONNECTOR_URL` at the second service, and run `scripts/bootstrap.py`
once. `REDIS_URL` may be left empty — caching degrades to none, and says so in the
logs rather than failing.

---

## Route 3 — a single VM

For a 2 vCPU / 4 GB Ubuntu box.

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Code
git clone https://github.com/<you>/buildwise-agentic.git
cd buildwise-agentic && cp .env.example .env

# 3. Production settings
cat >> .env <<'EOF'
APP_ENV=prod
JWT_SECRET=$(openssl rand -hex 32)
EOF

# 4. Build the console into the image, then start
docker compose build --build-arg BUILD_WEB=true api
docker compose up -d
docker compose exec api python scripts/bootstrap.py
docker compose exec api python scripts/selfcheck.py
```

With `APP_ENV=prod` the demo token endpoint and the `X-Actor-Id` development header
both stop working — which means **you must wire real authentication before this is
reachable from the internet.** That refusal is deliberate.

### A reverse proxy in front

```nginx
server {
    listen 443 ssl;
    server_name buildwise.example.com;

    ssl_certificate     /etc/letsencrypt/live/buildwise.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/buildwise.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Port 8100 must **not** be exposed publicly. The mock systems of record enforce
scope but have no authentication of their own — they stand in for internal systems
that would sit inside a private network.

---

## Environment reference

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `prod` disables the demo auth shortcuts |
| `DATABASE_URL` | local Postgres | Required |
| `REDIS_URL` | local Redis | Optional; empty disables connector caching |
| `MOCK_CONNECTOR_URL` | `http://localhost:8100` | Where the systems of record live |
| `LLM_PROVIDER` | `mock` | `mock` · `anthropic` · `openai` |
| `ANTHROPIC_API_KEY` | empty | Only for `anthropic` |
| `EMBEDDING_PROVIDER` | `local` | `local` needs no key and no network |
| `JWT_SECRET` | dev value | **Change for any deployment** |
| `CLASSIFICATION_CONFIDENCE_THRESHOLD` | `0.70` | Below this, a human is involved |
| `AGENT_CONFIDENCE_THRESHOLD` | `0.70` | Same, for specialist findings |

---

## Troubleshooting

**`make bootstrap` cannot reach Postgres.**
`docker compose ps` — wait for `healthy`, then retry. Bootstrap is idempotent.

**The console loads but says the API is unreachable.**
`curl localhost:8000/health`. If that fails, `docker compose logs api`. The usual
cause is a prompt or policy file failing validation at boot, which is intentional:
a missing prompt version should stop a deploy, not surface on a customer's case.

**Answers say information is unavailable for everything.**
The corpus was not ingested. `make ingest`, then `make selfcheck`.

**Empty approval queue.**
Nothing has been tiered ≥2 yet. Send the possession-dispute message as Rakesh
Menon, or the engineer's site note as Meera Iyer.

**Retrieval feels slow on the free Postgres tier.**
No pgvector, so cosine runs in Python. `/health` reports `dense_mode`. Fine at this
corpus size; install pgvector for a real deployment.

**Build fails at `pip install` with "package directory 'api' does not exist".**
Fixed. An early version of the Dockerfile ran `pip install "."` before copying the
source, so setuptools looked for a package that was not there yet. Dependencies now
install from `requirements.txt` and the project is not pip-installed at all —
`PYTHONPATH=/app` makes the packages importable directly. If you are seeing this,
you have an old Dockerfile.

**`api` container exits immediately / "service api is not running".**
Get the reason first: `docker compose logs api`.

One cause is fixed in this version: when the image is built with `BUILD_WEB=false`,
an empty `web/dist` directory is created so the COPY stage has something to copy.
The app tested for that directory and then mounted `web/dist/assets`, which does not
exist — and StaticFiles raises at construction, so the process died before uvicorn
bound a port. It now gates on `web/dist/index.html`, which is what actually
indicates a real build. If you see this, your image predates the fix.

Note that the API does **not** need the schema to exist in order to start, so
`bootstrap` runs after the container is up. If you would rather not depend on the
service being healthy, run it as a one-off instead — this works even when the
service is down:

```powershell
docker compose run --rm api python scripts/bootstrap.py
```

**Port already in use.**
Edit the `ports:` mappings in `docker-compose.yml`, or stop the conflicting service.
