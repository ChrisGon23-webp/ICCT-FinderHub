# ICCT FinderHub — Responsive Full-Stack Starter (VS Code + Supabase + Render)

This folder now contains a responsive Flask web app, Supabase Auth + PostgreSQL + Storage integration, and a protected admin dashboard. The older single-file visual prototype is preserved in `prototype/index.html`.

> **Project status:** learning / school-project starter. Test with sample data first. Get permission before describing it as an official ICCT service. The uploaded-photo bucket is public in this starter, so upload generic item photos only—not IDs, faces, phone numbers, private documents, or other sensitive information.

## 1. Folder structure

```text
icct-finderhub/
├── app.py                    # Flask routes, auth flow, reports, claims, admin actions
├── requirements.txt          # Python dependencies
├── .env.example              # Environment-variable template; copy to .env
├── .gitignore                # Excludes .env and Python cache
├── render.yaml               # Render Web Service configuration
├── README.md
├── sql/
│   └── schema.sql            # Tables, profile trigger, RLS, Storage bucket
├── templates/                # Mobile-responsive HTML pages
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── report.html
│   ├── my_reports.html
│   ├── my_claims.html
│   └── admin.html
├── static/css/
└── prototype/
    └── index.html            # Earlier browser-only prototype
```

## 2. Requirements

- Python 3.11 or 3.12 recommended
- VS Code
- A Supabase project
- A GitHub repository for Render deployment

## 3. Set up Supabase first

1. Create a project at <https://supabase.com/> and save the database password somewhere private.
2. In Supabase, open **SQL Editor → New query**.
3. Open `sql/schema.sql`, copy all of it, paste it into the SQL Editor, then click **Run**.
4. Open **Project Settings → API Keys** (or the project's **Connect** dialog) and copy:
   - Project URL
   - Publishable key (usually starts with `sb_publishable_`; older projects may show an `anon` key)
   - Secret key for backend only (usually starts with `sb_secret_`; older projects may show `service_role`)
5. The SQL creates `profiles`, `items`, `claims`, and `activity_logs`, enables Row Level Security, creates a profile for new Auth users, and creates the `item-photos` public Storage bucket.
6. In **Authentication → URL Configuration**, set the Site URL to your local address during local testing, then update it to your Render URL after deployment. If you enable email confirmation, users must verify their email before signing in.

**Never put the Supabase secret/service-role key in `index.html`, browser JavaScript, GitHub, or a screenshot.** The Flask backend uses it server-side. The publishable key is designed for client-side use, but this app currently uses it only for Supabase Auth HTTP requests from Flask.

## 4. Create your local `.env`

In VS Code, open the project root folder. Copy `.env.example` and rename the copy to exactly `.env` (not `.env.txt`). Replace the placeholder values:

```dotenv
FLASK_SECRET_KEY=PASTE_A_LONG_RANDOM_SECRET_HERE
FLASK_DEBUG=true
SESSION_COOKIE_SECURE=false
MAX_UPLOAD_MB=4

SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_your_real_key
SUPABASE_SERVICE_ROLE_KEY=sb_secret_your_real_secret
SUPABASE_STORAGE_BUCKET=item-photos
```

- `FLASK_SECRET_KEY`: signs Flask session cookies. Generate a random value in PowerShell with `python -c "import secrets; print(secrets.token_hex(32))"` and paste the result after `=`.
- `FLASK_DEBUG`: `true` for local debugging only; use `false` on Render.
- `SESSION_COOKIE_SECURE`: `false` for `http://127.0.0.1` local testing; set `true` on the HTTPS Render deployment.
- `MAX_UPLOAD_MB`: maximum uploaded image size.
- `SUPABASE_URL`: your project's URL, not the dashboard URL.
- `SUPABASE_PUBLISHABLE_KEY`: publishable key from Supabase API Keys; older projects can use the `anon` key here.
- `SUPABASE_SERVICE_ROLE_KEY`: server-only secret key; older projects may call this `service_role`. Do not expose it.
- `SUPABASE_STORAGE_BUCKET`: must match the bucket name created by `schema.sql` (`item-photos`).

Do not add quotation marks around ordinary values unless they contain spaces. Do not commit `.env`. `.gitignore` is configured to ignore it.

## 5. Run it in VS Code (Windows PowerShell)

Open the project folder in VS Code, then choose **Terminal → New Terminal**:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, you can run the venv Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5000>. The health endpoint is <http://127.0.0.1:5000/health>. Create a student account, sign in, submit a sample report, and confirm it appears in Supabase tables.

## 6. Make the first admin account

1. Register your own account through the app first.
2. In Supabase, open **Table Editor → profiles** and confirm your account exists.
3. Open **SQL Editor** and run this query, replacing the email with the exact email you registered:

```sql
update public.profiles
set role = 'admin'
where email = 'your-own-registered-email@example.com';
```

4. Sign out and sign in again. The Admin link should appear in the navigation.

New registrations always get the `student` role. Do not add a public form that lets users choose `admin`. Only a trusted project owner should promote an account through the Supabase dashboard/SQL editor.

## 7. Admin functions included

- Overview cards for report and claim counts
- All submitted items, including available photo links and current status
- Change item status: pending review, approved, rejected, turned over, claimed, resolved, archived
- View all registered profiles and roles
- Review claim proof and approve/reject a claim; approval marks the item as claimed
- Recent activity log for administrative status/claim decisions

The current starter supports `student` and `admin` role behavior; `staff` is reserved in the schema for a future iteration. Notifications are not yet email/SMS/push notifications. The app writes the main admin decisions to `activity_logs`.

## 8. Deploy to Render

1. Push this project to GitHub, making sure `.env` is not tracked. Check with `git status` before pushing.
2. In Render, choose **New → Web Service**, connect your GitHub repository, and use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
3. Add these environment variables in Render's **Environment** settings. You can also use the included `render.yaml` Blueprint:
   - `FLASK_SECRET_KEY`: a long random secret (Render Blueprint can generate it)
   - `FLASK_DEBUG`: `false`
   - `SESSION_COOKIE_SECURE`: `true`
   - `MAX_UPLOAD_MB`: `4`
   - `SUPABASE_URL`: your project URL
   - `SUPABASE_PUBLISHABLE_KEY`: publishable / legacy anon key
   - `SUPABASE_SERVICE_ROLE_KEY`: backend-only secret / legacy service-role key
   - `SUPABASE_STORAGE_BUCKET`: `item-photos`
4. Deploy and open `https://YOUR-SERVICE.onrender.com/health`. It should return JSON with `status: ok` and `supabase_configured: true`.
5. Update Supabase Auth's Site URL to the Render URL. Test register, sign in, report, image upload, admin review, and claim approval.

Render reads environment variables from its dashboard at runtime; do not rely on uploading your local `.env` to GitHub. See the official [Render environment variable guide](https://render.com/docs/configure-environment-variables) and [Flask deployment guide](https://render.com/docs/deploy-flask).

## 9. Mobile responsiveness

The Flask templates use responsive Tailwind layouts, a mobile navigation menu, stacked forms, responsive cards, and horizontally scrollable management tables for narrow screens. Test at browser widths around 360px, 390px, 768px, and desktop. Keep buttons large enough to tap and avoid placing private user details on public pages.

## 10. Security and limitations

- This is a starter for learning and needs security review before real campus use.
- Flask forms include CSRF tokens. Admin routes check the role server-side.
- The backend-only secret bypasses Supabase RLS, so the Flask routes must always enforce authorization. Do not expose the key or create public routes that use it without checks.
- The starter's Storage bucket is public to make listing photos easy to display. Use generic photos only. For production, prefer a private bucket and signed URLs, plus file-content validation and moderation.
- Add rate limiting, email verification, password reset, account suspension, stricter validation, monitoring, backups, and notification delivery before public launch.
- The admin list currently loads up to 250 items/users/claims. Add pagination for larger deployments.
- No real student record system integration is included.
