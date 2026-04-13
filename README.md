# Retainr (Multi-Business MVP)

Retainr helps businesses recover lost members and increase revenue automatically.

## Stack

- Backend: Python (Flask) + SQLite
- Frontend: HTML + JavaScript + CSS

## What this build includes

- Business registration and login (`/register`, `/login`)
- Multi-tenant data isolation (each business sees only its own members/check-ins/notifications)
- Business-specific public check-in link and QR (`/checkin/<token>`)
- Dashboard:
  - Stats (Total, Active, At Risk, Lost, Revenue at Risk, Today's Check-Ins)
  - Notification bar (check-ins, duplicate check-in attempts, message-needed alerts)
  - In-dashboard quick messaging to members (status/at-risk/lost/promo/custom)
  - Message template editor
  - Business/social profile editor (used on public check-in page)
  - Check-in QR download button
- Members management:
  - Create, edit, delete
  - Filter and search
  - Mark visit manually
  - Bulk open WhatsApp chats for selected members
- Public check-in:
  - Phone lookup
  - Existing member quick check-in
  - New member registration + check-in
  - Prevents second check-in on same day
  - Logs check-in time in West African time (`Africa/Lagos`)

## Core routes

- Auth:
  - `GET /login`, `POST /api/auth/login`
  - `GET /register`, `POST /api/auth/register`
  - `POST /api/auth/logout`
- Dashboard & admin:
  - `GET /dashboard`
  - `GET /members`
  - `GET /member-form`
  - `GET /my-checkin` (redirects to business tokenized public check-in page)
- Public check-in:
  - `GET /checkin/<token>`
  - `GET /api/public/checkin/context/<token>`
  - `POST /api/public/checkin/lookup`
  - `POST /api/public/checkin/submit`

## Database tables

- `gyms` (business accounts)
- `members`
- `member_checkins`
- `gym_notifications`

`init_database()` handles table creation and legacy migration for older single-business data.

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Configure environment variables:

```bash
set DB_PATH=retainr.sqlite3
set PORT=5000
set SECRET_KEY=change-this-secret
```

3. Run:

```bash
python app.py
```

4. Open:

- Register business: `http://localhost:5000/register`
- Login: `http://localhost:5000/login`
- Public check-in: use each business's generated link from dashboard

## Status engine

- `Lost`:
  - membership expired (`expiry_date < today`), or
  - no visit for 30+ days
- `At Risk`:
  - no visit for 7+ days, or
  - expiry within 7 days
- `Active`:
  - otherwise
