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

## Phase 3 — Insights & export

- **What counts as spending:** receipts that are `ready` and have both a `purchase_date` and a
  `total`. They're bucketed by purchase date, a plain calendar date with no timezone math. "This
  month" defaults to the current UTC month. Refunds (negative totals) reduce the totals.
- **Endpoint shapes.**
  - `summary` adds `needs_review_count` (all-time) so the dashboard needs one call.
  - `change_pct` is `null` when the previous month is zero, since a percentage of nothing is
    meaningless.
  - `by-category` takes inclusive `from`/`to` (both optional) and lists uncategorized spending as
    `category_id: null`.
  - `trend` takes `months` (1–36) and an optional `end=YYYY-MM`. It always returns every month in
    the window, zero-filled, and adds a per-category breakdown with `by_category=true`.
- **Budgets.** `GET /budgets` reports spending for the current month (or `?month=`). Status is
  `warning` from the alert threshold up to and including 100%, and `over` only *above* 100%,
  matching "amber at the threshold, red above 100%". `PUT` upserts. Deleting a category removes
  its budget (cascade).
- **CSV export.**
  - Rows are streamed from a server-side cursor in batches of 500, one per ready receipt, oldest
    first, undated last.
  - Columns are exactly the spec's.
  - Excel compatibility: UTF-8 BOM (so "Café" survives Excel), CRLF line endings, tags joined with
    "; ", and newlines in notes collapsed to spaces.
  - Formula injection: text cells starting with `= + - @` get a leading `'`. Numeric columns are
    never touched, so a refund still exports as `-5.00`.
  - Same filters as the spec (`from`, `to`, `category_id`, plus `none`).
- **Charts follow the data-viz method.**
  - The default category colors were re-seeded from a palette validated for color-blind
    separation (8 hues in a fixed order; Travel gets a darker blue and Other a neutral gray, since
    a 9th hue can't validate). This only affects new users.
  - Category colors are user-editable, so charts never rely on color alone. The donut always has a
    legend table with names, amounts and shares. The trend has a "Show as table" view. Budget bars
    pair the status color with an icon and a label ("✓ On track", "▲ Near limit", "! Over budget").
  - The donut shows at most 6 segments (the top 5 plus "Everything else"), drops non-positive
    categories, and has 2px surface gaps between segments.
  - The trend is a single series in one hue with rounded data ends and a hover tooltip.
  - Month labels use "Jan ’26" style, so they can't be read as "January 26th".
- **Exports are plain links** (`<a href="/api/export/csv?…" download>`): the cookie
  authenticates them and the browser handles the download natively.
- **E2E isolation.** Playwright starts its own API (:8100) and Next dev server (:3100) against a
  separate `receipts_e2e` database. `scripts/ensure_database.py` creates it if missing, then
  migrations run. The test sets the purchase date to the 15th of the current UTC month, so it
  lands in "this month" on the dashboard regardless of when it runs.
- **Bug fixed: edits during processing were overwritten.** The background task loaded the receipt,
  waited on extraction, then saved its stale copy, which overwrote anything the user changed in
  the meantime, including `user_edited_fields`. Now extraction runs first, then the row is
  re-read with `SELECT … FOR UPDATE` before results are applied. Mutating receipt endpoints also
  lock the row. Regression tests cover an edit and a delete made mid-extraction.
- **Bug fixed: `CORS_ORIGINS` from `.env` crashed startup.** pydantic-settings JSON-decodes list
  fields from the environment, so the comma-separated value in `.env.example` failed. The field is
  now `NoDecode` with an explicit parser that accepts comma-separated values or a JSON array. A
  test loads `.env.example` itself.

## Phase 4 — Production

- **AWS services added** (approved for this phase): SQS + DLQ, S3 event notifications, SES, RDS
  Postgres, App Runner (API), ECS Fargate (worker), ECR (image), Secrets Manager, VPC with one NAT
  gateway, CloudWatch alarms, SNS (ops email) and AWS Budgets.
- **Dependencies added:** `fpdf2` (PDF drawing; brings in Pillow, which also downscales receipt
  photos), `pypdf` (appends receipts uploaded as PDFs), and for `infra/`, `aws-cdk-lib` and
  `constructs`. Rate limiting and JSON logging are built in rather than adding `slowapi` or
  `python-json-logger`. **Sentry was skipped** (optional in the spec); JSON logs in CloudWatch
  cover the basics.

### Async pipeline
- **The S3 event is the upload trigger.** In queue mode (`SQS_QUEUE_URL` set) the API never
  enqueues uploads, because doing so as well as the S3 event would process every upload twice and
  pay Textract twice. Reprocessing has no S3 event, so the API sends
  `{"type": "reprocess", "receipt_id": ...}`. Queue mode requires `STORAGE_MODE=s3`, and settings
  refuse anything else.
- **`/complete` is idempotent** (it was a 409 before). The S3 event can reach the worker before
  the browser calls `/complete`; the worker treats an existing upload as complete and starts, and
  `/complete` just reports the current state.
- **Idempotency and duplicates.** The worker skips receipts already `ready` and leaves `failed`
  ones for an explicit reprocess. A per-receipt Postgres advisory lock, held on a dedicated
  connection across processing, stops two workers extracting the same receipt when SQS delivers a
  message twice. Tests show three deliveries cost one Textract call.
- **What reaches the DLQ.** Messages are deleted only after handling. Infrastructure errors and
  unparseable messages are retried, and after 3 receives they move to the DLQ, which is alarmed.
  Extraction failures *don't* go there: they mark the receipt `failed` with a user-facing message,
  because retrying a bad photo won't help.
- **Visibility timeout** is 3 minutes, longer than any extraction. The worker finishes in-flight
  messages on SIGTERM (ECS stop timeout 60s) and scales 1–4 tasks on queue depth.

### Budget alerts
- **When checks run:** after a receipt finishes processing, after a PATCH changes a receipt's
  total, date or category, and after a budget is created or changed (lowering a limit can cross
  the threshold). Only the **current** month alerts; an email about last month is noise.
- **At most once per category per month.** This is enforced by a unique
  `(category_id, month)` row in `budget_alerts`, inserted with `ON CONFLICT DO NOTHING` and
  committed before the email is sent. Concurrent checks can't both send (tested with 5 in
  parallel), and a failed send is logged, not retried. If the first crossing is already over
  100%, the single email says "over budget".
- **Email modes:** `EMAIL_MODE=log` in development (logs instead of sending) and `ses` in
  production. Plain-text email keeps it simple and spam-filter-friendly.

### PDF report
- `GET /export/pdf` takes the same filters as the CSV export. It has a summary page (total, by
  category, every receipt), then one page per image. Receipts uploaded as PDFs have their own
  pages appended.
- Images are re-encoded to JPEG at 1600px max, so a month of 10 MB photos stays a few MB.
  Attachments are capped at the first 100 receipts (the report says so); unreadable files get a
  note instead of failing the report.
- The built-in PDF fonts are Latin-1: curly quotes and dashes are mapped to ASCII, and anything
  else outside Latin-1 becomes "?". Bundling a Unicode TTF would fix it at the cost of about 700 KB.

### Hardening
- **Rate limits** are fixed-window counters in Postgres (`rate_limits`, one upserted row per
  key), so limits hold across every App Runner instance without adding Redis:
  - login: 20 per 5 min per IP and 10 per 15 min per email;
  - signup: 10 per hour per IP;
  - upload URLs: 120 per 10 min per user.

  Responses are 429 with `Retry-After`. The worker prunes stale counters hourly.
- **Client IP:** `X-Forwarded-For` is only trusted for `TRUSTED_PROXY_HOPS` hops (production: 2,
  Vercel then App Runner), reading from the right so a client can't choose its own rate-limit key.
- **Logs:** `LOG_FORMAT=json` writes one object per line (timestamp, level, logger, message,
  extra fields, exception) and routes uvicorn's loggers the same way.

### Infrastructure (`infra/`)
- **Where things run:**
  - API on **App Runner** (as the spec suggests), egressing through a VPC connector.
  - Worker on **ECS Fargate**, because App Runner only runs request-driven services, not
    long-polling consumers.
  - Both use the same image (`backend/Dockerfile`, non-root, JSON logs); the worker overrides the
    command.
- **Network:** public, private-with-egress (API connector and worker) and isolated (RDS)
  subnets. One NAT gateway (about $32/month) keeps AWS API access simple, and a free S3 gateway
  endpoint keeps S3 traffic off the NAT.
- **Least privilege**, checked by `infra/tests`:
  - API: S3 put/get/delete on `users/*`, send to the queue, SES send from the one identity, read
    its two secrets.
  - Worker: S3 get, consume the queue, SES send, read the database secret only (not the JWT key).
  - The only `*` resources are `textract:AnalyzeExpense` and `ecr:GetAuthorizationToken`, which
    AWS doesn't allow scoping, plus CDK's log-retention helper.
- **Database credentials:** the RDS-generated secret is injected whole as `DATABASE_SECRET`, and
  the app builds the URL from it (URL-escaping the password), because App Runner can't inject
  individual JSON keys.
- **Frontend on Vercel**, not Amplify. It needs no infrastructure, and the `/api` rewrite keeps
  cookies first-party. CORS on the bucket allows the frontend origin for direct uploads and image
  loads.
- **Deploy workflow:** GitHub OIDC (no stored AWS keys). It runs after CI succeeds on `main`, or
  manually, and does nothing until `AWS_DEPLOY_ROLE_ARN` is set, so pushes don't fail before AWS
  is configured.
- **Not deployed by me:** the stack is synthesized and tested here (`cdk synth`, CloudFormation
  assertions), but no AWS account was touched.

## After Phase 4

- **Renamed to Stub.** The product name, package names (`stub-api`, `stub-web`, `stub-infra`), the
  Docker Compose project, the CDK stack (`Stub`, with resources tagged `app=stub`) and the default
  bucket name all changed. The database is still called `receipts` because it describes the data.
  The original SPEC.md was later removed from the repo.
- **Demo receipts** (`demo-receipts/`) are generated by `backend/scripts/make_demo_receipts.py`
  from the mock Textract responses, so each file looks like the data the mock returns for it.
  The mock extractor recognizes them by SHA-256 (`mock_responses/demo_index.json`) and uses the
  date printed on the file. Dates are relative to when the script ran, so the dashboard has
  current data; rerun to refresh. Two samples were added: a Starbucks receipt with a
  low-confidence total (to show review) and a CVS PDF.
- **Mock mode no longer invents data for real receipts.** It used to give any non-demo upload a
  random sample, which looked like a misread of the user's receipt. Now such files come back
  empty (needs review) unless `MOCK_UNKNOWN_FILES=sample`, which the test suite sets. `/api/health`
  reports `textract_mode`, and the app shows a demo-mode banner while it's `mock`.
