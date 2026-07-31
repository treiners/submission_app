# Assignment Submission System

A small web app for students to submit files (report + AMPL code, or whatever
you configure) with name/student ID, get a confirmation email + 4-character
code, and give you an admin page to browse submissions.

## What's included

- `app.py` — Flask application (routes, validation, submission logic)
- `db.py` — SQLite schema and queries
- `storage.py` — storage backends (local / Dropbox / OneDrive), pluggable
- `email_util.py` — Gmail SMTP confirmation email
- `config.json` — submission rules (areas, allowed file types, size/count limits) — edit freely
- `.env.example` — secrets template (copy to `.env`, never commit `.env`)
- `templates/`, `static/` — the submission form and admin pages
- `get_dropbox_refresh_token.py` — one-time helper for Dropbox setup

## 1. Local setup

```bash
cd submission_app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
- Set `SECRET_KEY` to a long random string.
- Set `ADMIN_USERNAME` / `ADMIN_PASSWORD`.
- Leave `STORAGE_BACKEND=local` to start — this works immediately, no extra setup.

Run it:
```bash
python3 app.py
```
Visit `http://localhost:5000` for the form, `http://localhost:5000/admin` for the admin page.

The SQLite database is created automatically at `instance/submissions.db` on first run.

## 2. Configuring submission rules

Edit `config.json` — no code changes needed:

```json
{
  "assignment_title": "Assignment 1 Submission",
  "areas": [
    {
      "key": "report",
      "label": "Report",
      "allowed_extensions": [".docx", ".pdf"],
      "max_size_mb": 10,
      "max_files": 1
    },
    {
      "key": "ampl_code",
      "label": "AMPL Code",
      "allowed_extensions": [".zip"],
      "max_size_mb": 10,
      "max_files": 1
    }
  ]
}
```
Add more areas, change limits, or allow multiple files per area (`max_files > 1`) as needed.
Restart the app after editing.

## 3. Email (Gmail)

Gmail requires an **App Password** (not your normal password) for SMTP:
1. Turn on 2-Step Verification on the Gmail account: https://myaccount.google.com/security
2. Generate an app password: https://myaccount.google.com/apppasswords
3. In `.env`, set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` to that address/app password.

If email sending fails for any reason, the submission still succeeds and the
code is still shown/stored — email is best-effort, the code is the reliable
fallback.

## 4. Storage backend

### Local (default, works out of the box)
Files land in a per-submission folder with one directory per configured area:

```text
uploads/<student_id>_<name>_<code>/
  report/<stored-file>
  ampl_code/<submitted-zip>
  ampl_code/<file>.mod
  ampl_code/<file>.dat
  ampl_code/<file>.run
  ampl_code/other/<other-files>
  metadata/<area>_<stored-file>.json
```

For an AMPL ZIP submission, the original ZIP is retained. Its `.mod`, `.dat`,
and `.run` files are also extracted into `ampl_code/`; all other archive files
are extracted into `ampl_code/other/`. Archive directory names are not trusted,
and duplicate filenames receive a numeric suffix.

The metadata sidecars are kept on the same local device as the uploaded files.
They include file size, MIME type, SHA-256 checksum, filesystem timestamps, and
archive contents where applicable. Word documents additionally include OOXML
core properties, paragraph/table/image/hyperlink counts, word count, macro
presence, and the document package entry count.

Nothing in `uploads/` or `instance/` should be committed to version control.

## 5. AMPL analysis

The admin submission page includes an AMPL analysis view. Selecting **Run all
.run files** executes each discovered `.run` file with `amplpy`, using the
submission's `ampl_code/` directory as its working directory. Results are
stored locally under:

```text
uploads/<student_id>_<name>_<code>/analysis/<run-name>/
  result.json
  stdout.txt
  stderr.txt
```

Install the Python dependency with `python -m pip install -r requirements.txt`.
The worker imports `AMPL` from the `amplpy` Python library and calls
`modules.load()`; it does not invoke an `amplpy` command. Install the required
AMPL and solver modules in the same Python environment, activate the UUID
license there using the AMPL modules setup, and optionally set `AMPL_PATH` for
an existing AMPL installation. If `amplpy` is installed in a different Python
environment from Flask, set `AMPL_PYTHON` to that interpreter, for example:

```text
AMPL_PYTHON=/opt/homebrew/anaconda3/bin/python
```

Each result includes a diagnostics section showing the interpreter, Python
version, installed `amplpy` version/path information, module-load status,
`AMPL_PATH`, and import/runtime errors. Set `AMPL_RUN_TIMEOUT_SECONDS` in
`.env` to control the maximum runtime for each script. A first statistics
object is stored with each result; additional model statistics can be added
later without changing the upload format.

Analysis runs are admin-triggered and execute sequentially. Uploaded AMPL
scripts are untrusted input: use this feature only on a controlled local
machine until a process or container sandbox is added.

### Dropbox
1. Create an app at https://www.dropbox.com/developers/apps
   - Choose **Scoped access**, then **Full Dropbox** or **App folder**
   - Under **Permissions**, enable `files.content.write` and `files.content.read`
2. Run the helper script to get a long-lived refresh token:
   ```bash
   python3 get_dropbox_refresh_token.py
   ```
3. Put the printed `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
   into `.env`, and set `STORAGE_BACKEND=dropbox`.

If the Dropbox upload ever fails at submission time (bad token, network issue,
etc.), the app automatically falls back to local storage for that submission
and flags it in the admin view — no submission is ever lost.

### OneDrive
Not wired up yet — it needs an Azure AD app registration (`Files.ReadWrite.All`,
application permission, admin-consented), which usually needs your IT/tenant
admin. The implementation sketch is in `storage.py` (`OneDriveStorage` class)
ready to complete once you have those credentials. Until then, keep
`STORAGE_BACKEND` set to `local` or `dropbox`.

## 5. Deploying on your own server

Don't use the Flask dev server in production. Use gunicorn behind Nginx:

```bash
pip install gunicorn
gunicorn -w 2 -b 127.0.0.1:8000 app:app
```

Example Nginx config (adjust domain/paths):
```nginx
server {
    listen 443 ssl;
    server_name submissions.yourdomain.edu;

    ssl_certificate     /etc/letsencrypt/live/yourdomain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain/privkey.pem;

    client_max_body_size 100M;

    location /static/ {
        alias /path/to/submission_app/static/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
HTTPS is important here since the form captures IP addresses and personal data.

Run the app as a systemd service so it survives reboots, e.g.:
```ini
[Unit]
Description=Assignment Submission System
After=network.target

[Service]
WorkingDirectory=/path/to/submission_app
Environment="PATH=/path/to/submission_app/venv/bin"
ExecStart=/path/to/submission_app/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

## 6. Backing up

The whole system's state is `instance/submissions.db` (SQLite) plus, if using
local storage, the `uploads/` folder. Back both up regularly (e.g. a nightly
cron job copying them off-server).

## Notes / things worth knowing

- Confirmation codes are 4 characters from `A-Z2-9` excluding `0/O/1/I` to avoid
  visual ambiguity, and checked for uniqueness against the database.
- IP address, user agent, and submission timestamp are stored with every
  submission (visible in the admin detail page).
- The admin page is protected by a single username/password in `.env`. For anything
  beyond casual use, consider adding this behind your server's own auth too
  (e.g. HTTP Basic Auth at the Nginx level, or restricting by campus VPN/IP).
