# Decisions

Choices made where the spec was ambiguous or silent. Newest at the bottom of each phase.

## Phase 0 — Scaffolding

- **Repo root.** The spec's tree shows a `receipt-tracker/` folder; this repository's root plays
  that role rather than nesting another directory. The git repo is initialized here.
- **Full schema in the initial migration.** §5 fully defines the data model, so all SQLAlchemy
  models and the initial Alembic migration were created now instead of piecemeal per phase.
  Later phases add migrations only for changes.
- **Merchant search index.** Used a `pg_trgm` GIN index on `receipts.merchant` (the spec allows
  trigram or full-text). Trigram supports case-insensitive partial matches via `ILIKE`, which
  §9 Phase 2 requires. The migration runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`.
- **Global merchant rules uniqueness.** `merchant_category_rules` has
  `UNIQUE (user_id, merchant_pattern) NULLS NOT DISTINCT` (Postgres 15+) so two global rules
  (`user_id IS NULL`) can't share a pattern.
- **`line_items.quantity` is `NUMERIC(12,3)`.** Quantities can be fractional (e.g. 1.235 lb);
  money columns stay `NUMERIC(12,2)`.
- **Cascades.** Deleting a user cascades to their data; deleting a category sets
  `receipts.category_id` to NULL (per §7) and cascades to that category's budgets and rules.
- **`/health` is a liveness check only.** It doesn't touch the database, so it stays cheap and
  doesn't fail when Postgres is briefly unavailable.
- **Test database.** docker-compose creates a separate `receipts_test` database on first start
  so pytest won't touch dev data. (Phase 0 has no DB-backed tests yet; CI applies, checks and
  rolls back the migrations against a real Postgres service.)
- **Makefile.** Added so local setup is two commands (`make setup`, `make dev`). `make` is
  preinstalled on macOS/Linux, so this adds no project dependency. The README also lists the
  raw commands.
- **Frontend test deps.** Added Vitest, React Testing Library, jsdom and Prettier (+ the
  Tailwind plugin and `eslint-config-prettier`) now, since Phase 0 requires lint and tests in CI.
  Recharts, TanStack Query, React Hook Form and Zod will be added in the phases that use them.
- **pnpm build approval.** pnpm 12 refuses unapproved install scripts. `unrs-resolver` (pulled
  in by `eslint-config-next`) is allowed in `frontend/pnpm-workspace.yaml`; its script only
  verifies its native binary.
- **Placeholder home page.** `/` shows an API status indicator that calls `/api/health` through
  the Next.js rewrite. It will be replaced by the dashboard and auth redirect in Phase 1.

## Phase 1 — Accounts, upload, extraction, review

- **Dependencies added.** Backend: `argon2-cffi` (argon2 hashing), `pyjwt` (JWT), `boto3`
  (S3/Textract), `python-multipart` (FastAPI's form parser, needed by the local upload stand-in),
  and `moto` for tests. Frontend: TanStack Query, React Hook Form, Zod, `@hookform/resolvers`
  (the RHF–Zod bridge) and `@testing-library/user-event`. All are named in or implied by the spec's
  stack. I avoided `email-validator` by validating email format with a simple regex.
- **Local uploads mirror S3 presigned POSTs.** `upload-url` returns `{upload_url, fields}` in both
  modes; locally `fields` holds a short-lived signed token, so the browser code is identical for
  local and S3. The token is a form field rather than a query parameter so it never shows up in
  access logs.
- **Receipt images.** In S3 mode `GET /receipts/{id}` returns a presigned GET URL (5 min). In
  local mode it returns `/api/receipts/{id}/file`, which checks ownership with the session
  cookie. That endpoint also exists in S3 mode and redirects to a fresh presigned URL.
- **Mock extractor.** It picks one of three bundled sample responses
  (`app/services/mock_responses/`) based on a hash of the storage key, so a given receipt always
  gets the same data and reprocessing is stable. `MOCK_TEXTRACT_DELAY_SECONDS` (default 1.5)
  makes the processing state visible; tests set it to 0.
- **Parsing rules** (`parsing.py`):
  - When a summary type appears more than once (Textract often reports "Total" and "Balance due"),
    the highest-confidence value that parses wins.
  - Money: with both `,` and `.`, the last one is the decimal separator. A lone `.` is always
    decimal (fuel prices like `3.459`). A lone `,` is decimal only when followed by 1–2 digits
    (`12,50`), otherwise thousands (`1,234`). Trailing `-` and parentheses mean negative.
  - Dates: the normalized value Textract sometimes provides is used first. Otherwise US month-first
    is tried before day-first, so `03/04/2024` is March 4 but `15/03/2024` still parses. Years
    before 2000 are rejected as OCR noise.
  - A line item with a unit price and no amount gets `unit_price × quantity`.
  - ALL-CAPS merchant names are title-cased ("KROGER" → "Kroger").
- **needs_review arithmetic check.** "Line items + tax + tip ≈ total" runs when every line item has
  an amount and tax and total are known. A missing tip counts as 0; requiring a tip line would mean
  the check almost never runs.
- **User edits.** `PATCH` records a field in `user_edited_fields` only when its value actually
  changes, so a client resending unchanged values doesn't lock fields. Replacing line items records
  `line_items`. Reprocessing skips everything recorded. Edited fields count as fully confident when
  `needs_review` is recomputed.
- **Confirming a receipt** is `PATCH {"needs_review": false}`; the UI's Confirm button sends that,
  together with any pending edits.
- **`low_confidence_fields`** in the detail response lists the extracted fields below
  `LOW_CONFIDENCE_THRESHOLD` that the user hasn't edited. The server owns the threshold, so the
  frontend has no copy to keep in sync.
- **Validation errors** are flattened into the `{"detail": "message"}` shape, e.g.
  `"email: Enter a valid email address; password: String should have at least 8 characters"`.
- **Status codes.** A wrong type or size on `upload-url` returns 400. Reprocessing or completing in
  the wrong state returns 409. A category the user doesn't own returns 422 ("Category not found").
  Someone else's receipt is always 404.
- **Receipts list** hides `pending_upload` rows, which are abandoned or in-flight uploads. Cursor
  pagination is keyset-based on `(sort column DESC NULLS LAST, created_at, id)`. Filters arrive in
  Phase 2.
- **Delete order.** The stored file is deleted first, then the row. If S3 fails, the row stays and
  the user can retry, so no file is left orphaned without a row.
- **Auth redirects.** Next.js middleware checks only whether the cookie is present; the API
  verifies the JWT. On a 401 the client calls `/auth/logout` to clear the stale cookie before
  redirecting to `/login`; otherwise middleware would bounce it straight back. The `next`
  parameter only accepts same-site paths.
- **Login timing.** Login verifies against a dummy hash when the email is unknown, so response
  time doesn't reveal which emails have accounts.
- **Default categories are seeded at signup** (in Phase 1, though they're first used in Phase 2)
  so every user has them from the start.
- **Toasts, dialogs and zoom are hand-rolled** (small components, native `<dialog>`) rather than
  adding UI libraries.
- **Multi-file upload** came for free with the upload page, so Phase 1 already uploads up to 3
  files concurrently, each with its own progress bar and error.
