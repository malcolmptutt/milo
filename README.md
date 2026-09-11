# MiLO PoC — Deployment Walkthrough

Explicit, click-by-click version. Assumes you're comfortable with a
terminal and already have accounts on Google Cloud, Neon, GitHub, and
Vercel — just not necessarily with what each one's UI wants from you.

Do the phases in order. Don't skip ahead — later phases need values
you generate in earlier ones.

---

## Phase 1 — Database (Neon)

1. Go to `console.neon.tech` and open (or create) a project.
   - **New Project** → name it `milo-poc` → pick any region → **Create Project**.
2. On the project's dashboard/overview page there's a **Connection string**
   panel (sometimes labelled **Connection Details**). It looks like:
   ```
   postgresql://neondb_owner:AbC123xyz@ep-something.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
   Click **Show password** if it's masked, then copy the *whole* string.
   Paste it into a scratch text file for now — you'll need it in Phase 3.
3. In the left sidebar, click **SQL Editor**.
4. Open `schema.sql` from the unzipped project (any text editor) and copy
   its entire contents.
5. Paste into the SQL Editor and click **Run**.
6. Click **Tables** in the sidebar and confirm you now see `users`,
   `oauth_tokens`, and `tasks`. If they're not there, the paste or run
   silently failed — try again.

---

## Phase 2 — Google OAuth

Google reorganized this UI: the old "OAuth consent screen" page is now
**Google Auth Platform**, split into four tabs — **Branding**,
**Audience**, **Data Access**, **Clients**. Redirect URIs live under
**Clients**, not "Credentials" (that old page is gone/renamed).

1. Go to `console.cloud.google.com`. Check the project selector at the
   top of the page — make sure it's the project you want this in (or
   create a new one there first).
2. Left menu (☰) → **APIs & Services** → **Library**. Search
   **Google Calendar API** → open it → **Enable**. (Skip if it already
   shows "Enabled".)
3. Left menu → **APIs & Services** → **Google Auth Platform**.
   - If this is your first time here, it walks you through **App
     name** (`MiLO`), **User support email**, **Developer contact** —
     fill those in, choose **External** as the user type.
4. Click the **Audience** tab → under **Test users** → **+ Add users**
   → enter your own Google account email → **Save**. Without this,
   Google refuses to let you sign in, since the app isn't publicly
   verified.
5. Click the **Clients** tab → **Create Client**.
6. **Application type**: `Web application`. **Name**: `MiLO PoC`.
7. Leave **Authorized JavaScript origins** blank — that's for
   browser-only apps, not this one.
8. Under **Authorized redirect URIs** → **+ Add URI** → paste exactly:
   ```
   http://localhost:3000/api/auth/google/callback
   ```
9. **Create**.
10. Google shows your **Client ID** and **Client secret** once. Copy
    both into your scratch file now — the secret isn't shown again.
    If you lose it later, use **Reset secret** on the client's page in
    the **Clients** tab to generate a new one.

---

## Phase 3 — Run it locally

```bash
# unzip wherever you keep projects, then:
cd milo-poc
cp .env.example .env
```

Open `.env` in a text editor and fill in every value:

```
GOOGLE_CLIENT_ID=<from Phase 2 step 9>
GOOGLE_CLIENT_SECRET=<from Phase 2 step 9>
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/google/callback
FRONTEND_URL=http://localhost:3000/
SESSION_SECRET=<any random string — see command below>
DATABASE_URL=<the full connection string from Phase 1 step 2>
```

Generate a random session secret rather than typing something by hand:
```bash
openssl rand -hex 32
```
Paste that output as `SESSION_SECRET`.

Now install the Vercel CLI if you don't have it, and run the app:
```bash
npm install -g vercel
vercel dev
```
First run: it opens your browser to log in, then asks a few questions
about linking the folder to a Vercel project — accept the defaults
("set up and deploy", link to a new project, accept the detected
settings). Once it prints `Ready! Available at http://localhost:3000`,
open that URL.

Click **Connect Google**, sign in with the *same* Google account you
added as a test user in Phase 2, and grant calendar access. You should
land back on the app, signed in, with your next 7 days of events
listed. **Fix anything that breaks here before moving to Phase 4** —
it's far easier to debug locally than on a live deployment. See
Troubleshooting at the bottom if something doesn't work.

---

## Phase 4 — Push to GitHub and deploy

```bash
git init
echo ".env" >> .gitignore
git add .
git commit -m "Initial MiLO PoC"
```

Check `.env` is NOT about to be committed:
```bash
git status
```
It should not appear in the list. If it does, your `.gitignore` didn't
take — check the file has a plain line reading `.env` in it, then
`git add .gitignore` and commit again.

Create a new **empty** repository on GitHub (don't let it add a
README or .gitignore — you already have code), then push:
```bash
git remote add origin https://github.com/<your-username>/milo-poc.git
git branch -M main
git push -u origin main
```

In the Vercel dashboard: **Add New...** → **Project** → find `milo-poc`
in the list → **Import**.

On the configuration screen, **before clicking Deploy**, expand
**Environment Variables** and add all six from your `.env` file
(`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`,
`FRONTEND_URL`, `SESSION_SECRET`, `DATABASE_URL`). For the redirect
URI and frontend URL, it's fine to paste the localhost values for now
— you'll fix them in Phase 5, right after you learn your real domain.

Click **Deploy**. When it finishes, Vercel shows your live URL, e.g.
`https://milo-poc-yourname.vercel.app`. Copy it.

---

## Phase 5 — Point everything at the real domain

1. Vercel dashboard → your project → **Settings** → **Environment
   Variables**.
2. Edit `GOOGLE_REDIRECT_URI` → `https://<your-domain>/api/auth/google/callback`
3. Edit `FRONTEND_URL` → `https://<your-domain>/`
4. Go to the **Deployments** tab → **...** menu on the latest one →
   **Redeploy**. (Environment variable edits only take effect after a
   redeploy.)
5. Back in Google Cloud Console → **APIs & Services** → **Google Auth
   Platform** → **Clients** tab → click your OAuth client's name.
6. Under **Authorized redirect URIs** → **+ Add URI** → paste:
   ```
   https://<your-domain>/api/auth/google/callback
   ```
   (Keep the localhost one too — don't remove it, it's still useful
   for local testing later.)
7. **Save**.

---

## Phase 6 — Test the deployed app

1. Open your live Vercel URL.
2. **Connect Google** → sign in → allow access.
3. Confirm you land back signed in, events visible.
4. Add a task by typing, and by tapping the mic button and speaking.

---

## Troubleshooting

**"redirect_uri_mismatch" error from Google** — the URI Google is
seeing doesn't *exactly* match one you registered (trailing slash,
`http` vs `https`, or a typo). Compare character-for-character against
what you added in Phase 2/5.

**500 error on any `/api/...` call** — check the logs: Vercel dashboard
→ your project → **Deployments** → click the deployment → **Functions**
tab → click the function → view logs. Usually a missing or misspelled
environment variable.

**"DATABASE_URL is not set" error** — you either didn't add it in
Vercel's Environment Variables, or added it after the last deploy and
haven't redeployed since (env var changes need a redeploy).

**Login works but no calendar events show up** — double check you
enabled the Calendar API in Phase 2 step 2, and that your Google
account is listed as a test user under the **Audience** tab in
Google Auth Platform (Phase 2 step 4).

**`vercel dev` complains about the project not being linked** — run
`vercel link` first and follow the prompts, then try `vercel dev` again.

## Known PoC limitations (by design, not oversights)

- Single Google Calendar only (`primary`) — no Microsoft 365 yet.
- Voice input creates a task from the raw transcript; it doesn't parse
  intent ("move my 3pm to Thursday" won't do anything smart yet).
- No pattern learning — that layer comes after there's real usage data.
- `psycopg2` opens a fresh connection per request, fine at PoC traffic
  levels but the first thing to revisit (e.g. Neon's built-in pooler)
  if this moves past PoC.
# milo
