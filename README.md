# Shaha Finlease — Loan Management System

A working, demo-ready LMS for Shaha Finlease's **recovery** business: purchased NPA / written-off
portfolios (personal loans and credit cards) are uploaded, allocated to callers across the
**Jogeshwari, Dadar and Bangalore** offices, and worked through calls, promises to pay (PTP) and payments.

**Live demo:** https://shaha-finlease-lms.netlify.app  (first visit after idle takes ~1 minute to wake) ·
**Code:** https://github.com/aaradhya1205/shaha-lms

> Ships with dummy seed data. Python 3.11+ · FastAPI · SQLAlchemy 2 · SQLite (PostgreSQL-ready) · server-rendered Jinja pages.

---

## 1. Quick start (one command)

```bash
./run.sh            # creates .venv, installs deps, seeds demo data if none, starts http://localhost:8000
./run.sh --reset    # wipe and re-seed the demo (users + 10,000 accounts + 2 weeks of activity), then start
```

Other ways to run it:

| Command | What it does |
|---|---|
| `make reset` | same as `./run.sh --reset` |
| `make seed` / `python -m app.seed` | reset the database only (about 5 s) |
| `python -m app.seed --no-activity` | users + 10,000 **fresh, unallocated** accounts (clean slate) |
| `make test` | run the 35 automated tests |
| `make big-csv` | generate `data/accounts_100000.csv` for the 1,00,000-row upload test |
| `PORT=8765 ./run.sh` | use another port if 8000 is busy |

To use PostgreSQL instead of SQLite, set `DATABASE_URL=postgresql+psycopg://user:pass@host/db` and `pip install psycopg[binary]`.

### Demo logins (password for everyone: `Shaha@123`)

| Role | Username | Sees |
|---|---|---|
| Head of Collections | `head` | everything, all 3 offices; upload, allocate, dashboard |
| COO | `coo` | same as Head |
| Manager (7) | `manager1` … `manager7` | their team's callers' accounts + unallocated accounts of their office |
| Caller (60) | `caller1` … `caller60` | **only** accounts allocated to them (their work queue) |
| Customer service (3) | `cs1` `cs2` `cs3` | look-up of their office's accounts and payment entry |

`manager1` (Rekha Khan, Jogeshwari) manages `caller1`–`caller9`. The full roster is in `data/users_seed.csv`.

---

## 2. The 10-minute demo story

| # | Who | Step | What it shows |
|---|---|---|---|
| 1 | `head` | **Dashboard**: book of 10,000 accounts, recovery %, office roll-up, caller league table | Head sees all offices |
| 2 | `head` | **Upload** → choose `data/demo_upload_250.csv` | 250 imported, 1 duplicate skipped, 5 bad rows reported line by line (downloadable CSV) |
| 3 | `head` | Click **Allocate these 250 accounts** → tick a few rows, or pick "All 250 matching" → choose 1 caller or several (round-robin) → **Allocate** | Bulk allocation; caller workload shown next to each name |
| 4 | `manager1` | **Accounts**: only their team + unallocated Jogeshwari accounts; open a Dadar loan by URL → 404 | Role scoping on the server |
| 5 | `caller1` | **My Queue**: counters (due today, overdue, never called); rows ordered PTP-due-today → follow-up today → overdue → new → upcoming | Today's follow-ups and promises first |
| 6 | `caller1` | **Start calling** → account page → click **Promise to Pay** → **Save & next** (2 clicks; amount and date are pre-filled) | Call + PTP in ≤ 3 clicks; jumps to the next account |
| 7 | `caller1` | Back on that account → **Record payment** (partial) | Outstanding unchanged, total paid ↑, status **Part-paid**, payment counted towards the PTP |
| 8 | `caller1` | Pay the rest, or tick **Full & final settlement** | Status **Closed** / **Settled** |
| 9 | `head` | **Allocation** → filter "Owned by caller1" → reassign one account to `caller2` → open it | Reassignment keeps every call, PTP and payment; the move appears in Activity |
| 10 | any | Broken promises: seeded promises whose date has passed already show as **Broken**, and those accounts are back on top of the queue | Automatic PTP → Broken |

Optional: show time passing with `LMS_TODAY=2026-10-20 ./run.sh`. Every pending promise dated before
that day turns Broken on the first request.

Keyboard shortcuts on the caller side: `N` start/next in queue · `/` search · `1`–`9` pick disposition · `⌘/Ctrl + Enter` save & next.

---

## 3. Feature checklist (all 9 must-haves)

| # | Feature | Done when | Where | Verified by |
|---|---|---|---|---|
| 1 | Login, role-based access | Each role sees only its own data | `app/security.py`, `app/permissions.py` | `tests/test_auth_and_access.py` (10 tests: caller can't read/write others' accounts by URL, manager limited to team/office, 403 on supervisor screens) |
| 2 | Upload CSV | 1,00,000 rows load | `app/services/upload.py`, `/upload` | `test_one_lakh_rows_load`: **1,00,000 rows in ~4 s** via HTTP; re-upload skips all 1,00,000 as duplicates in ~1.6 s |
| 3 | List & search | Find by name, phone, loan no. | `app/services/accounts.py`, `/accounts` | `test_search_by_name_phone_and_loan` (partial matches, case-insensitive) |
| 4 | Account page | Customer, loan, outstanding, promises and payments in one place | `/accounts/{id}` | `test_account_page_shows_everything` |
| 5 | Allocation | Select many → assign; reassign keeps history | `app/services/allocation.py`, `/allocation` | `test_reassign_keeps_history`, `test_bulk_allocate_round_robin` |
| 6 | Caller queue | Today's follow-ups and promises first | `queue_bucket()` + `order_query()` | `test_queue_puts_todays_promises_and_followups_first` |
| 7 | Log a call | Disposition, remarks, next follow-up in ≤ 3 clicks | `app/services/calls.py` + account page | `test_call_with_only_a_disposition_is_enough`: disposition → Save = **2 clicks** |
| 8 | Promise to pay | Amount and date saved; Broken if unpaid by the date | `app/services/ptp.py` | `test_ptp_saved_then_kept_by_payment`, `test_unpaid_ptp_becomes_broken_after_its_date` |
| 9 | Record payment | Outstanding unchanged, total paid ↑; Part-paid / Closed / Settled | `app/services/payments.py` | `test_payments_part_paid_then_closed`, `test_settlement`, `test_payment_validation` |

Five screens as specified: **Login, Upload, Account list with search (= caller queue), Account page, Allocation**,
plus a small **Dashboard** for Head and managers.

---

## 4. Design

### Architecture
```
Browser ──HTML forms──▶ FastAPI routers (app/routers/*)     thin: parse input, check role, call a service, render
                              │
                              ▼
                        Services (app/services/*)           all business rules: upload, allocation, calls, PTP, payments, queue
                              │
                              ▼
                        permissions.scope_accounts()        one row-level filter used by every account query
                              │
                              ▼
                        SQLAlchemy models (app/models.py) ─▶ SQLite / PostgreSQL
```
* **Server-rendered pages** (Jinja2) with a little vanilla JS for speed-ups such as keyboard shortcuts and
  select-all. There is no build step. Typography is Inter + JetBrains Mono (Google Fonts, with system-font fallback).
* **Role checks are on the server.** Every account read or write goes through
  `permissions.scope_accounts()` / `get_visible_account()`. An account you can't see returns **404**,
  so its existence is not revealed. Screens a role can't use return **403**.
* **Passwords** are hashed with **scrypt** and a random per-user salt (Python stdlib). Sessions use a
  signed, `HttpOnly`, `SameSite=Lax` cookie that holds only the user id.
* **Money is stored in integer paise**, so there are no floating-point rounding errors. It is shown in Indian format (₹1,25,200).

### Data model
| Table | Key columns |
|---|---|
| `offices` | name |
| `users` | code, name, username, password_hash, role, office_id, manager_id |
| `accounts` | loan_no (unique), customer, mobile, office, product, portfolio, **outstanding** (never changes), **total_paid**, **status**, **owner_id** (caller); queue fields `next_followup_date`, `ptp_date`, `ptp_amount`, `last_call_at`, `call_count` |
| `allocation_history` | account, from_user, to_user, allocated_by, at, note (append-only) |
| `call_logs` | account, user, disposition, remarks, next_followup_date, at |
| `ptps` | account, amount, promised_date, paid_amount, status (Pending / Kept / Broken / Cancelled) |
| `payments` | account, amount, payment_date, mode, reference, is_settlement, ptp_id |
| `upload_batches` | file, who, rows read / imported / duplicates / failed, duration, full error report |

The queue fields on `accounts` duplicate data from `ptps` and `call_logs` on purpose. That way the
caller queue is a single indexed query on one table, and it stays fast at 1 lakh+ accounts.

### Status rules
```
New ──first call──▶ Working ──PTP──▶ PTP ──payment──▶ Part-paid ──…──▶ Closed   (total paid ≥ outstanding)
                       ▲               │                                Settled  (payment flagged full & final)
                       └── PTP Broken ─┘  (back to Working, or Part-paid if something was paid)
```
* **PTP.** One open promise per account; a new promise cancels the old one. Payments dated on or before
  the promised date count towards it, and it becomes **Kept** once the amount is covered. If it is still
  Pending after its date, a sweep marks it **Broken** and the account returns to the top of today's
  queue. The sweep runs once per business day, on the first request of that day. It is idempotent and
  can also be called directly (`sweep_broken`).
* **Payment.** Must be > 0, no more than the balance due, and not dated in the future. `outstanding`
  is never modified; only `total_paid` grows.
* **Queue order.** PTP due today → follow-up due today → overdue (missed follow-up or promise) → never
  called → upcoming. Within each group, the earliest date comes first, then the highest balance.
  "Save & next" opens the highest-priority account not yet called today.

### Upload pipeline
The file is streamed with `csv.DictReader`, so it is never fully held in memory as rows. Each row is
validated, de-duplicated against the database and within the file, and inserted in 5,000-row bulk
`INSERT`s inside one transaction. Bad rows are skipped and reported with their line number and reason;
the full error report is downloadable. Accepted variants: `₹`/commas in amounts, `+91` prefixes, and
`DD-MM-YYYY` dates.

---

## 5. Assumptions (made where the brief was open)

1. **Roles.** The brief names three roles (Caller, Manager, Head). The seed file also contains a **COO**
   (treated like the Head) and **Customer Service** users (office-scoped look-up and payment entry, but
   they cannot log calls or allocate).
2. **Manager scope** = accounts owned by their own callers **plus unallocated accounts of their office**,
   because a manager has to see accounts before allocating them. Managers can allocate only to their own callers.
3. **Head can allocate across offices** (e.g. to balance load); managers cannot.
4. **Upload is Head/COO only.** Uploaded accounts always start as **New** and unallocated; the CSV
   `status` column is ignored. An existing loan number is **skipped, never overwritten**, so re-uploading a file is safe.
5. **Settlement**: negotiating and approving the settlement amount is out of scope. A payment ticked
   "full & final settlement" closes the account as **Settled**.
6. **Closed/Settled** accounts leave the queue and accept no more calls, promises or payments.
   Payment reversal is out of scope.
7. **Promise limits**: amount ≤ balance due, date between today and 90 days ahead.
8. **Default follow-ups** per disposition (editable before saving): Callback / RNR / Switched off +1
   day, Settlement / Claims paid +2, Refused +3, Dispute / Wrong number +7, PTP = promise date.
9. Users in `users_seed.csv` without a username get `head` / `coo`. All demo users share one password
   (`DEMO_PASSWORD`, default `Shaha@123`).
10. **Seed data.** `python -m app.seed` loads `data/accounts_10000.csv` through the same importer as the
    Upload screen. It then allocates about 70% of the accounts to callers in the matching office and
    simulates two weeks of calls, promises and payments (fixed random seed, so it is reproducible), so
    every screen has something to show. The other ~30% stay unallocated for the allocation demo.
11. The **business date** is today's date unless `LMS_TODAY` is set.

---

## 6. Tests

```bash
make test        # 35 tests, ~7 s, uses a throw-away SQLite DB
```
Covers all 9 features, including server-side access control by direct URL, the 1,00,000-row load,
queue ordering, PTP Kept/Broken, and every payment status transition.

Measured on a laptop (SQLite): 1,00,000-row upload ≈ 4 s; search across 1,10,000 accounts ≈ 0.2 s;
other pages 10–60 ms.

## 7. Production settings & deployment

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` → secure cookies, HSTS, demo-login box hidden, `SECRET_KEY` required |
| `SECRET_KEY` | — | signs the session cookie (required in production) |
| `DATABASE_URL` | SQLite file | e.g. PostgreSQL in production |
| `SHOW_DEMO_LOGINS` | `1` in dev, `0` in prod | show the demo-login helper on the sign-in page |
| `ALLOWED_HOSTS` | — | extra domains allowed to submit forms (e.g. a proxy domain) |
| `DEMO_PASSWORD` | `Shaha@123` | password given to seeded users |

Built in: security headers (CSP, X-Frame-Options, nosniff, Referrer-Policy, HSTS), cross-site POST
blocking (Origin check + SameSite cookies), login lock-out after 5 failures in 15 minutes, `no-store`
on pages with customer data, `/healthz` for load balancers, a logged and branded 500 page, and a
non-root Docker image.

```bash
docker build -t shaha-lms . && docker run -p 8000:8000 -e SECRET_KEY=$(openssl rand -hex 32) shaha-lms
```
`render.yaml` deploys the same image on Render in one click (Blueprint). The container seeds the demo
data on first start (`python -m app.seed --if-empty`).

**Live hosting.** Netlify serves static files and JS/Go functions only, so the Python app runs on Render and
`deploy/netlify/` is a tiny Netlify site in front of it: `_redirects` proxies every path to Render, and
`index.html` is a branded start-up screen that waits for the free-tier Render instance to wake (~1 min
after idle) before opening the login page. On the free tier the disk is ephemeral, so the demo data
re-seeds whenever the instance restarts.

## 8. Project layout
```
app/
  main.py            app, middleware (session, daily PTP sweep), error pages
  config.py          settings + business clock (today/now)
  db.py, models.py   engine, tables
  security.py        password hashing, current user, role guard
  permissions.py     row-level scoping (who sees which accounts)
  money.py           paise <-> rupees, Indian number format
  services/          upload, allocation, accounts (search/queue), calls, ptp, payments
  routers/           auth, dashboard, accounts, upload, allocation
  templates/, static/
  seed.py            one-command demo reset
data/                users_seed.csv, accounts_10000.csv, demo_upload_250.csv
scripts/generate_accounts.py   dummy CSV generator (e.g. 1,00,000 rows)
tests/               pytest suite
```

## 9. What I'd do next
Per-form CSRF tokens (today: Origin check + SameSite cookies), Alembic migrations, PostgreSQL with trigram indexes for
name search, background job for very large uploads with progress, a scheduled nightly PTP sweep,
audit log of logins, payment approval and reversal workflow, a settlement module, click-to-call
dialer integration, SMS/WhatsApp payment links, and purchase-price tracking to report recovery against cost.
