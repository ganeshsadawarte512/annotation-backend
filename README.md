# Annotation API (FastAPI backend)

Backend for the login → dashboard → annotation flow: JWT auth with two roles
(`admin`, `annotator`), games list, and per-game possession/event logging.
Admin-only actions (adding games, adding/removing possessions, uploading
video) are enforced **server-side** in `app/deps.py` (`require_admin`) — not
just hidden in the UI.

## Run locally (SQLite, zero setup)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python seed.py                  # creates admin/coder1 demo users + sample games
uvicorn app.main:app --reload
```

API docs (interactive): http://localhost:8000/docs

Demo logins created by `seed.py`:
- `admin` / `changeme123` (change this password immediately — see below)
- `coder1` / `changeme123`

## Using Postgres instead of SQLite (production)

`psycopg2-binary` isn't in the base `requirements.txt` since it's not needed
for local SQLite dev, and its precompiled wheels can lag behind brand-new
Python releases. When you're ready to point at Postgres:

```bash
python -m pip install -r requirements-postgres.txt
```

If that also fails to build on your Python version, use `psycopg` (v3) instead,
which has better wheel coverage for newer Python releases:
`python -m pip install "psycopg[binary]"` — then change `DATABASE_URL` to start
with `postgresql+psycopg://` instead of `postgresql://`.

## Run with Docker + Postgres

```bash
docker compose up --build
docker compose exec api python seed.py
```

## Key endpoints

| Method | Path                          | Access          |
|--------|-------------------------------|-----------------|
| POST   | `/auth/login`                 | public          |
| GET    | `/auth/me`                    | any logged-in   |
| GET    | `/games`                      | any logged-in   |
| POST   | `/games`                      | **admin only**  |
| GET    | `/games/{id}`                 | any logged-in   |
| POST   | `/games/{id}/video`           | **admin only**  |
| GET    | `/games/{id}/possessions`     | any logged-in   |
| POST   | `/games/{id}/possessions`     | **admin only**  |
| DELETE | `/possessions/{id}`           | **admin only**  |

`/auth/login` takes form data (`username`, `password`) and returns a JWT.
Send it back as `Authorization: Bearer <token>` on every other request.

## Deploying (recommended: Render or Railway)

1. Push this folder to a GitHub repo.
2. On Render/Railway: create a new **Web Service** from the repo (they auto-detect the Dockerfile), and a separate **PostgreSQL** instance.
3. Set environment variables on the web service:
   - `DATABASE_URL` — copy the connection string from the Postgres instance
   - `JWT_SECRET` — generate with `openssl rand -hex 32`
   - `STORAGE_BACKEND=local` to start (see below for going to S3/R2)
4. After first deploy, run `python seed.py` once via the platform's shell/console to create your real admin account — **then change that password** (there's no self-service password-change endpoint yet; add one before giving this to real users, or update it directly via `python -c` using `hash_password`).
5. Point your frontend's API base URL at the deployed service.

## Moving video storage to S3 / Cloudflare R2

Everything routes through `app/storage.py`. To switch:
1. `pip install boto3` (add to `requirements.txt`)
2. Set in `.env`: `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_ENDPOINT_URL` (R2 gives you this), `S3_ACCESS_KEY`, `S3_SECRET_KEY`
3. No route code changes needed — `get_storage()` picks the backend automatically.

R2 is worth a look over AWS S3 here: no egress fees, which matters once
annotators are scrubbing through video repeatedly.

## What's deliberately left out (add before real users touch this)

- **Password reset / change-password endpoint** — right now only `seed.py` sets passwords.
- **Rate limiting on `/auth/login`** — add e.g. `slowapi` before this is public.
- **Refresh tokens** — access tokens currently just expire (8h default) and require re-login.
- **Alembic migrations** — `Base.metadata.create_all()` is fine for getting started, but once you have real data, switch to Alembic migrations for schema changes instead of editing `models.py` directly.
- **Video transcoding to HLS** — the dashboard mockup showed `hls`/`mp4` links; this backend stores whatever file you upload as-is. If you want adaptive HLS streaming, that's a separate transcoding step (e.g. via `ffmpeg` in a background job) — happy to add this when you're ready.
