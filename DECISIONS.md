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

## Phase 2 — Organizing

- **Global rules name a category instead of pointing at one.** §5 gives
  `merchant_category_rules` a `category_id` with `user_id NULL` meaning global, but categories are
  per-user, so a global rule can't reference one. Global rules store `category_name` (e.g.
  "Groceries") and resolve to the user's category with that name, case-insensitively. A check
  constraint enforces it: user rules have `category_id` and global rules have `category_name`.
  If the user renames or deletes that default category, the global rule simply stops matching for
  them.
- **75 global rules** are seeded by the migration `db6313b997ee`. The patterns are frozen inside
  the migration rather than imported from app code, so the migration never changes after it ships.
  A test checks that each pattern is already normalized and names a default category.
- **Normalization** (`normalize_merchant`): lowercase; apostrophes and `&` are dropped without a
  space (`Joe's` → `joes`, `AT&T` → `att`); other punctuation becomes a space; `#123` and
  standalone numbers are removed; filler words (`inc`, `llc`, `ltd`, `co`, `corp`, `store`,
  `the`, `com`, …) are dropped.
- **Matching** is whole-word containment, and the longest pattern wins: `uber eats` (Dining) beats
  `uber` (Transport), and `shell` doesn't match "Shellfish Shack". The user's own rules are checked
  before global ones.
- **Learning.** When a PATCH changes a receipt's category to a non-null value, the user rule
  `normalized merchant → category` is upserted. Clearing a category teaches nothing.
- **Category counts as a user edit.** Changing it adds `category_id` to `user_edited_fields`, so
  reprocessing won't re-categorize. If the user corrects the merchant but never picked a category,
  the rules re-run for the corrected name.
- **Existing receipts aren't re-filed** when a rule is learned; rules apply to new receipts and
  reprocessing. Bulk re-filing could surprise people and the spec doesn't ask for it.
- **Categories list returns a plain array**, not `{items, next_cursor}`. A user has a handful of
  categories, so pagination would only add friction. Each item includes `receipt_count` for the
  delete confirmation.
- **Category names are unique case-insensitively** (409 on a clash), checked in the app; the DB
  constraint is case-sensitive.
- **Deleting a category** relies on the existing FKs: receipts become uncategorized
  (`SET NULL`); that category's budget and the user's rules pointing at it are removed
  (`CASCADE`).
- **Filters.**
  - `q` is a case-insensitive `ILIKE '%…%'` on merchant, with LIKE wildcards escaped; the pg_trgm
    index serves it.
  - `category_id=none` means uncategorized.
  - `tag` is an exact match on one tag.
  - Date and amount bounds are inclusive.
  - Every filter combines with AND and works with both sort orders and cursor pagination.
- **Thumbnails** use the same URL as the full image (no resizing pipeline). PDFs get a "PDF"
  placeholder. A resized thumbnail is a possible later improvement if lists get heavy.
- **Tags:** at most 50 per receipt and 40 characters each, trimmed and de-duplicated in order.
- **Filters live in the URL** (`/receipts?needs_review=true&q=kro`), so they survive a refresh
  and the Phase 3 dashboard can link to a filtered list. Malformed parameters are ignored, not
  surfaced as errors.
- **Tests build the schema with the real Alembic migrations** instead of `create_all`, so every
  test run also checks the migrations and gets the seeded global rules. Between tests, cleanup is
  `DELETE FROM users`, which cascades to user data and leaves global rules alone.
- **Alembic logging.** `env.py` now passes `disable_existing_loggers=False`; previously,
  running migrations in-process silenced the app's loggers.
