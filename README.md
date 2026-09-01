# Assignment Submission System

A small web app for students to submit files (report + AMPL code, or whatever
you configure) with name/student ID, get a confirmation email + 6-letter
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
- Set `PORT` if you want a port other than `5000`.
- Leave `STORAGE_BACKEND=local` to start — this works immediately, no extra setup.

Run it:
```bash
python3 app.py
```
Visit `http://localhost:<PORT>` for the form and `http://localhost:<PORT>/admin` for the admin page.

To run two local instances, for example:

```bash
PORT=5000 python3 app.py
PORT=5001 python3 app.py
```

The SQLite database is created automatically at `instance/submissions.db` on first run.

## 2. Configuring submission rules

Edit `config.json` — no code changes needed:

```json
{
  "assignment_title": "Assignment 1 Submission",
  "form_version": "0.9.1",
  "marking_template_docx": "making_template/marking_template_MATH5007_A1P1_2026_S2.docx",
  "marking_extraction_areas": ["report"],
  "marking_preview_max_images": 12,
  "areas": [
    {
      "key": "report",
      "label": "Report",
      "instruction": "Upload your report as a PDF or DOCX file.",
      "allowed_extensions": [".docx", ".pdf"],
      "max_size_mb": 10,
      "max_files": 1
    },
    {
      "key": "ampl_code",
      "label": "AMPL Code",
      "instruction": "Upload a single ZIP containing your AMPL .mod/.dat/.run files.",
      "allowed_extensions": [".zip"],
      "max_size_mb": 10,
      "max_files": 1
    }
  ]
}
```
`instruction` is optional and appears between the area label and upload box.
`form_version` is optional and appears at the very bottom of the public form page,
and also in admin page headers for quick confirmation of the live config.
`marking_template_docx` is optional and points to the DOCX template used to
extract answers for marking preview.
`marking_extraction_areas` is optional and lists area keys (for example `report`)
where DOCX answer extraction should run.
`marking_preview_max_images` is optional and limits how many embedded DOCX images
are included in the admin marking preview.
`marking_docx_pdf_converter` controls the PDF preview engine for DOCX files.
Use `auto` (default), `libreoffice` for a Word-independent conversion path,
`docx2pdf` if you want to rely on Microsoft Word on macOS, or `dxpdf` if you
want to use the separate Python library directly.
Add more areas, change limits, or allow multiple files per area (`max_files > 1`) as needed.
Restart the app after editing.

### Marking preview (DOCX, no markers)

When a DOCX is uploaded for an area listed in `marking_extraction_areas`, the app
compares it to the template DOCX and stores extracted answers as sidecar JSON in
the submission metadata folder. You can view this output in Admin via
**View marking preview** on the submission detail page.

The preview shows sequential extracted IDs (`Q1`, `Q2`, ...) and also keeps the
template order ID (`template Qn`) when they differ. This avoids numbering gaps
while still showing where each answer came from in the template.

### Submission formatting requirements (recommended)

To improve extraction quality and reduce manual correction during marking,
students should follow these formatting rules in the report template:

1. Keep each question prompt unchanged.
2. Start the answer on the next line or in a new paragraph.
3. Do not merge multiple question answers into one paragraph.
4. Do not delete question headings.
5. For image-only questions, add a short text marker such as
  "See image below".

The parser now tolerates many formatting variations (including prompt and answer
on one line), but these rules remain the most reliable approach across diverse
documents.

Embedded images from the DOCX are also extracted (up to the configured max) and
displayed inline in the same marking preview page.
Image links shown under each answer are now tied to the question where the image
appears in the original submission.

The marking preview page supports two review modes:
- **Per student**: all extracted answers for one submission, with previous/next
  submission navigation.
- **Per question**: one selected question at a time, with previous/next student
  navigation and a question button bar.

Recent UI behavior in marking preview:
- Split workspace with independent panes (left: marking, right: source document).
- Draggable divider; pane width is remembered in local storage.
- PDF is loaded by default when available; DOCX view remains selectable.
- Header controls stay visible while scrolling the marking pane.
- Keyboard shortcuts: `p` for previous, `n` for next.

Each answer now includes quick image links; selecting one opens a larger popup
preview for easier manual marking.

The page also includes marker fields for each extracted question:
- `score` (free-form, e.g. `4/5`)
- `comment` (marker notes)

Extraction confidence is shown per answer (`high`, `medium`, `low`) with a
numeric score and short reasons.

You can manually trigger **Re-extract marking preview**, but only when the
submission has no saved score/comment values. Once marking exists for a
submission, re-extraction is blocked to protect manual grading work.

If server-side submission processing fails after a submission record is created,
the record remains visible in Admin with status `failed` and a failure reason for
triage. The upload API now returns a specific reason string alongside the code.

For test cycles, Admin dashboard includes **Delete all submissions** (confirmation
required). This removes all submissions and uploaded files, and resets submission
numbering.

If `marking_template_docx` is not set, the app attempts auto-discovery using the
first matching file in `making_template/` or `marking_template/` with pattern
`marking_template*.docx`.

## Change log

Release notes are tracked in `CHANGELOG.md`.

### TODO (marking workflow improvements)

- Similar-answer checker per question (feasible)
  - Add a button on the marking page (for each question) such as "Find similar answers".
  - Compare the current answer against other students' answers for the same question and compute a similarity index.
  - Show a popup with the top matches (student ID, submission ID, similarity score, and answer snippet/full answer).
  - Suggested implementation path:
    - Start with a lightweight local method (for example TF-IDF + cosine similarity) for no external dependency on model APIs.
    - Optionally add semantic embeddings later for stronger paraphrase detection.
    - Add a configurable threshold (for example 0.80) and max results count.
    - Include simple safeguards: normalize whitespace/case and ignore very short answers.
  - Notes:
    - This should be a triage aid only, not an automatic misconduct decision.
    - Manual review remains essential before any academic integrity action.

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

- Confirmation codes are 6 letters from `A-Z` excluding `I/O` to avoid visual
  ambiguity, and checked for uniqueness against the database.
- IP address, user agent, and submission timestamp are stored with every
  submission (visible in the admin detail page).
- The admin page is protected by a single username/password in `.env`. For anything
  beyond casual use, consider adding this behind your server's own auth too
  (e.g. HTTP Basic Auth at the Nginx level, or restricting by campus VPN/IP).
