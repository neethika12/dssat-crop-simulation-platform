# Deploying

This app is split across two hosts, because the backend runs the real
compiled DSSAT-CSM Fortran engine (a long-running native process), which
Vercel's serverless functions can't do:

- **Backend** (FastAPI + the real DSSAT-CSM engine, in Docker) → **Render**
- **Frontend** (static HTML/JS dashboard) → **Vercel**

## 1. Backend on Render

1. Go to [render.com](https://render.com) and sign in with GitHub.
2. **New +** → **Web Service** → select this repo
   (`neethika12/dssat-crop-simulation-platform`, or whatever you named it).
3. Render detects `render.yaml` automatically (Docker runtime, free plan).
   Click **Deploy Web Service**.
4. First build takes ~5-8 minutes (compiling the real Fortran model from
   source). Once live, copy the service URL, e.g.
   `https://dssat-validation-api.onrender.com`.

Note: Render's free plan spins the service down after 15 minutes of
inactivity. The first request after idling takes ~30-60s to wake back up —
normal for a free tier, not a bug. Mention this if a professor tries it
cold.

## 2. Frontend on Vercel

1. Set the backend URL in the frontend config before deploying:

   ```bash
   # webapp/frontend/config.js
   window.DSSAT_API_BASE = "https://dssat-validation-api.onrender.com";
   ```

   Commit and push this change.

2. Go to [vercel.com](https://vercel.com) and sign in with GitHub.
3. **Add New** → **Project** → import this repo.
4. Vercel should pick up `vercel.json` (which points at `webapp/frontend`)
   automatically. Framework Preset: **Other**. No build command needed.
5. Click **Deploy**.

You'll get a URL like `https://dssat-crop-simulation-platform.vercel.app` —
that's the link to share.

## 3. Verify

Open the Vercel URL, pick an experiment, click **Run Validation** — if it
hangs or errors, open the browser dev tools Network tab and check the
`/api/validate` request is reaching the Render URL (not `localhost`), and
that Render's logs (on the Render dashboard) show the request arriving.
