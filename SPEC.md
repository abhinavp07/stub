# Receipt Scanner & Expense Tracker — Project Spec

> **For Claude Code:** This is the full specification for the project. Build it **phase by phase** (see "Build Phases"). Finish each phase, make sure it runs and its tests pass, and summarize what you did before starting the next one. When something here is ambiguous, choose the simplest option that satisfies the acceptance criteria and note the decision in `DECISIONS.md`. Ask before adding any dependency or AWS service not listed here.

---

## 1. Product Overview

A web app where users upload photos or PDFs of receipts. The app extracts the merchant, date, subtotal, tax, total and line items using **Amazon Textract (AnalyzeExpense)**, categorizes each receipt, and shows spending insights. Users can review and correct anything the extraction gets wrong.

**Core loop:** Upload receipt → automatic extraction → review/correct → see spending by category over time.

---

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| Charts | Recharts |
| Data fetching | TanStack Query |
| Forms/validation | React Hook Form + Zod |
| Backend | FastAPI (Python 3.12), Pydantic v2 |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL 16 (Docker locally, RDS in production) |
| File storage | Amazon S3 (private bucket, presigned URLs) |
| OCR | Amazon Textract `AnalyzeExpense` (via boto3) |
| Auth | FastAPI-issued JWT in an httpOnly cookie, passwords hashed with argon2 |
| Background work | FastAPI `BackgroundTasks` in Phases 1–3; SQS worker in Phase 4 |
| Backend tests | pytest, httpx `AsyncClient`, moto (for S3 mocking) |
| Frontend tests | Vitest + React Testing Library; Playwright for one end-to-end happy path |
| Python tooling | uv for dependencies, ruff for lint and format |
| JS tooling | pnpm, ESLint, Prettier |

---

## 3. Repository Structure

```
receipt-tracker/
├── SPEC.md
├── DECISIONS.md
├── README.md
├── docker-compose.yml          # postgres (+ api/web optional)
├── .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py             # FastAPI app, routers, CORS, exception handlers
│   │   ├── config.py           # pydantic-settings
│   │   ├── db.py               # async engine + session dependency
│   │   ├── models/             # SQLAlchemy models
│   │   ├── schemas/            # Pydantic request/response models
│   │   ├── routers/            # auth, receipts, categories, budgets, insights, export
│   │   ├── services/
│   │   │   ├── storage.py      # S3 presign / delete
│   │   │   ├── textract.py     # real + mock extractor behind one interface
│   │   │   ├── parsing.py      # Textract response -> normalized receipt
│   │   │   ├── categorize.py   # merchant -> category rules
│   │   │   └── processing.py   # orchestrates extraction for a receipt
│   │   ├── auth.py             # hashing, JWT, current_user dependency
│   │   └── worker.py           # Phase 4 SQS consumer
│   └── tests/
│       ├── fixtures/           # sample Textract JSON responses, sample images
│       └── ...
└── frontend/
    ├── package.json
    ├── next.config.ts          # rewrites /api/* -> FastAPI
    ├── src/
    │   ├── app/
    │   │   ├── (auth)/login/page.tsx
    │   │   ├── (auth)/signup/page.tsx
    │   │   ├── (app)/layout.tsx           # authenticated shell + nav
    │   │   ├── (app)/dashboard/page.tsx
    │   │   ├── (app)/receipts/page.tsx
    │   │   ├── (app)/receipts/[id]/page.tsx
    │   │   ├── (app)/upload/page.tsx
    │   │   ├── (app)/categories/page.tsx
    │   │   └── (app)/budgets/page.tsx
    │   ├── components/
    │   ├── lib/api.ts                     # typed fetch wrapper
    │   └── lib/types.ts
    └── tests/
```

---

## 4. Environment Variables

Provide a `.env.example` containing every variable below. **Never commit real secrets.**

```
# Backend
DATABASE_URL=postgresql+asyncpg://receipts:receipts@localhost:5432/receipts
JWT_SECRET=change-me
JWT_EXPIRES_MINUTES=10080
AWS_REGION=us-east-1
S3_BUCKET=receipt-tracker-dev-uploads
TEXTRACT_MODE=mock            # mock | aws
STORAGE_MODE=local            # local | s3
LOCAL_UPLOAD_DIR=./.uploads
CORS_ORIGINS=http://localhost:3000
MAX_UPLOAD_MB=10
LOW_CONFIDENCE_THRESHOLD=80
SQS_QUEUE_URL=                # Phase 4

# Frontend
API_BASE_URL=http://localhost:8000
```

**Local development must work with zero AWS credentials.** With `TEXTRACT_MODE=mock` and `STORAGE_MODE=local`, the app returns realistic fixture data and stores files on disk. The real AWS paths are switched on with `aws` / `s3`.

---

## 5. Data Model

All tables have `id UUID PK`, `created_at`, and `updated_at`. Money is stored as `NUMERIC(12,2)`, never float.

### users
| column | type | notes |
|---|---|---|
| email | text | unique, lowercased |
| password_hash | text | argon2 |
| display_name | text | nullable |
| currency | char(3) | default `USD` |

### categories
| column | type | notes |
|---|---|---|
| user_id | uuid FK users | |
| name | text | unique per user |
| color | text | hex color |
| is_default | bool | seeded defaults |

Seed these for each new user: Groceries, Dining, Transport, Gas, Shopping, Entertainment, Health, Utilities, Travel, Other.

### receipts
| column | type | notes |
|---|---|---|
| user_id | uuid FK users | indexed |
| s3_key | text | `users/{user_id}/receipts/{receipt_id}.{ext}` |
| original_filename | text | |
| content_type | text | image/jpeg, image/png, application/pdf |
| status | enum | `pending_upload`, `processing`, `ready`, `failed` |
| error_message | text | nullable |
| merchant | text | nullable |
| purchase_date | date | nullable |
| subtotal | numeric | nullable |
| tax | numeric | nullable |
| tip | numeric | nullable |
| total | numeric | nullable |
| currency | char(3) | |
| category_id | uuid FK categories | nullable |
| notes | text | nullable |
| tags | text[] | default `{}` |
| field_confidence | jsonb | e.g. `{"merchant": 99.1, "total": 72.4}` |
| needs_review | bool | true if any key field is below the threshold or missing |
| raw_extraction | jsonb | full Textract response, kept for debugging and reprocessing |
| user_edited_fields | text[] | fields the user corrected, so reprocessing never overwrites them |

Indexes: `(user_id, purchase_date DESC)`, `(user_id, category_id)`, plus a trigram or full-text index on `merchant`.

### line_items
| column | type | notes |
|---|---|---|
| receipt_id | uuid FK receipts | cascade delete |
| position | int | ordering |
| description | text | |
| quantity | numeric | nullable |
| unit_price | numeric | nullable |
| amount | numeric | nullable |

### merchant_category_rules
| column | type | notes |
|---|---|---|
| user_id | uuid FK users | nullable = global rule |
| merchant_pattern | text | normalized, lowercased |
| category_id | uuid FK categories | |

### budgets
| column | type | notes |
|---|---|---|
| user_id | uuid FK users | |
| category_id | uuid FK categories | unique with user_id |
| monthly_limit | numeric | |
| alert_threshold_pct | int | default 80 |

---

## 6. Key Flows

### 6.1 Upload (presigned URL flow)
1. The frontend calls `POST /api/receipts/upload-url` with `{filename, content_type, size_bytes}`.
2. The backend validates the type and size, creates a receipt with `status=pending_upload`, and returns `{receipt_id, upload_url, fields}` (a presigned POST with a content-length-range condition). In `STORAGE_MODE=local`, it returns a URL to a local FastAPI upload endpoint instead.
3. The browser uploads the file directly to that URL.
4. The frontend calls `POST /api/receipts/{id}/complete`.
5. The backend checks the object exists, sets `status=processing`, and schedules processing as a background task.

### 6.2 Processing
1. Call the extractor (`textract.py`) with the S3 object reference. The mock extractor returns a fixture JSON after a short artificial delay.
2. `parsing.py` normalizes the AnalyzeExpense response:
   - `SummaryFields` types to map: `VENDOR_NAME` (fall back to `NAME`), `INVOICE_RECEIPT_DATE`, `SUBTOTAL`, `TAX`, `GRATUITY`, `TOTAL` (fall back to `AMOUNT_PAID`).
   - `LineItemGroups[].LineItems[].LineItemExpenseFields` types: `ITEM`, `QUANTITY`, `UNIT_PRICE`, `PRICE`.
   - Parse money strings robustly (`$1,234.50`, `1.234,50`, a trailing `-`). Parse dates in common formats. Return `None` rather than crash when parsing fails.
   - Record each field's confidence in `field_confidence`.
3. Set `needs_review=true` if merchant, date or total is missing or below `LOW_CONFIDENCE_THRESHOLD`, **or** if the line items plus tax plus tip don't add up to within $0.05 of the total (when all of those values are present).
4. Auto-categorize (see 6.3).
5. Save everything and set `status=ready`. On any exception, set `status=failed` with a user-friendly `error_message`, and log the full traceback.

**`parsing.py` must be a pure function** with thorough unit tests against fixture JSON files. This is the riskiest code in the project.

### 6.3 Categorization
1. Normalize the merchant name (lowercase, strip punctuation, store numbers and suffixes like "#1234", "inc", "llc").
2. Check the user's own rules first, then global rules (seed around 40 common merchants: Walmart → Shopping, Shell → Gas, Starbucks → Dining, Kroger → Groceries, Uber → Transport, and so on).
3. If nothing matches, leave the category empty and let the user pick.
4. **Learning:** when a user changes a receipt's category, upsert a user rule mapping that merchant to the new category.

### 6.4 Auth
- `POST /api/auth/signup` and `POST /api/auth/login` set an httpOnly, `SameSite=Lax` cookie containing a JWT (with `Secure` in production). `POST /api/auth/logout` clears it.
- The `get_current_user` dependency protects every non-auth route.
- **Every query is scoped by `user_id`.** Requesting another user's receipt returns 404, never 403, so the app doesn't reveal that the receipt exists.
- Next.js uses `rewrites` to proxy `/api/*` to FastAPI, so the browser sees a single origin and cookies just work.
- Next.js middleware redirects unauthenticated users from `(app)` routes to `/login`.

---

## 7. API Endpoints

All routes are prefixed with `/api`. Responses are JSON. Errors use the shape `{"detail": "message"}`. List endpoints use cursor pagination: `?limit=25&cursor=...` returns `{items, next_cursor}`.

**Auth**
- `POST /auth/signup` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me`

**Receipts**
- `POST /receipts/upload-url`
- `POST /receipts/{id}/complete`
- `GET /receipts` — filters: `q` (merchant search), `category_id`, `date_from`, `date_to`, `min_total`, `max_total`, `status`, `needs_review`, `tag`; sort: `purchase_date` (default, descending) or `total`
- `GET /receipts/{id}` — includes line items and a short-lived presigned GET URL for the image
- `PATCH /receipts/{id}` — edit fields; adds edited field names to `user_edited_fields`; clears `needs_review` when the user confirms
- `PUT /receipts/{id}/line-items` — replace the whole list
- `POST /receipts/{id}/reprocess` — re-run extraction without overwriting user-edited fields
- `DELETE /receipts/{id}` — deletes the database row **and** the S3 object

**Categories**
- `GET /categories` · `POST /categories` · `PATCH /categories/{id}` · `DELETE /categories/{id}` (receipts in a deleted category become uncategorized)

**Budgets**
- `GET /budgets` (includes spent-this-month for each) · `PUT /budgets/{category_id}` · `DELETE /budgets/{category_id}`

**Insights**
- `GET /insights/summary?month=YYYY-MM` — total spent, receipt count, and comparison with the previous month
- `GET /insights/by-category?from=&to=`
- `GET /insights/trend?months=12` — monthly totals, optionally broken down by category

**Export**
- `GET /export/csv?from=&to=&category_id=` — streamed CSV

**Health**
- `GET /health`

---

## 8. Frontend Pages

| Route | Purpose |
|---|---|
| `/login`, `/signup` | Auth forms with Zod validation and clear error messages |
| `/dashboard` | This month's total vs last month, spending-by-category donut chart, 12-month trend bar chart, budget progress bars, "needs review" count linking to the filtered list |
| `/upload` | Drag-and-drop area for multiple files, a "Take photo" button on mobile (`accept="image/*" capture="environment"`), a per-file progress bar, and client-side type and size validation |
| `/receipts` | Filterable, searchable list or table: thumbnail, merchant, date, category chip, total, status badge, and a "needs review" flag. Infinite scroll |
| `/receipts/[id]` | Two-pane layout: the zoomable receipt image on the left, the editable form on the right. Low-confidence fields get an amber outline and a tooltip showing the confidence score. Line-item editor. Buttons for Confirm, Reprocess and Delete (with confirmation). Polls every 2s while status is `processing` |
| `/categories` | Create, rename and recolor categories |
| `/budgets` | Set a monthly limit per category |

**UX requirements**
- Responsive down to 375px wide.
- Loading skeletons, empty states with a call to action, and toasts for success and error messages.
- Format currency with `Intl.NumberFormat` using the user's currency.
- Accessible: labeled inputs, keyboard navigation, visible focus states.

---

## 9. Build Phases

Each phase lists its user stories and acceptance criteria. **A phase is done when every criterion passes and the tests are green.**

### Phase 0 — Scaffolding
- Monorepo layout as in §3, with docker-compose for Postgres.
- The FastAPI app boots and `/health` returns 200. Alembic is configured with the initial migration.
- Next.js boots with Tailwind and the `/api` rewrite working.
- `README.md` explains how to run everything locally in five commands or fewer.
- Ruff, ESLint and Prettier are configured. A GitHub Actions workflow runs lint and tests for both apps.

### Phase 1 — MVP: accounts, upload, extraction, review
**Stories**
- As a new user, I can sign up and log in, so my receipts are private.
- As a user, I can only ever see my own data.
- As a user, I can upload a receipt photo or PDF without typing anything.
- As a user, I can see that my receipt is processing, and whether it succeeded or failed.
- As a user, I get the merchant, date, subtotal, tax, total and line items filled in automatically.
- As a user, I can see the original image beside the extracted data.
- As a user, I can edit any extracted field.

**Acceptance criteria**
- [ ] Signup, login and logout work; protected pages redirect when logged out.
- [ ] Uploading a JPG, PNG or PDF of 10MB or less works. Other types and larger files are rejected on both the client and the server.
- [ ] Status moves `processing` → `ready` (or `failed` with a message). The detail page updates without a manual refresh.
- [ ] With `TEXTRACT_MODE=mock`, a realistic receipt appears with line items.
- [ ] With `TEXTRACT_MODE=aws`, a real receipt is extracted correctly. Verify by hand and document the steps in the README.
- [ ] Edits persist and show up after a refresh.
- [ ] Tests confirm that user A gets 404 for user B's receipt on every receipt endpoint.
- [ ] `parsing.py` has unit tests covering at least 5 fixture responses, including missing fields and odd money and date formats.

### Phase 2 — Organizing
**Stories**
- As a user, my receipts are auto-categorized.
- As a user, I can create my own categories.
- As a user, I can search and filter receipts by merchant, date, category and amount.
- As a user, I can add notes and tags.
- As a user, I can see which fields are uncertain, so I know what to double-check.
- As a user, I can delete a receipt, and its file is removed too.
- As a user, I can upload several receipts at once.

**Acceptance criteria**
- [ ] Seeded categories exist for new users; custom categories can be created, edited and deleted.
- [ ] Global merchant rules categorize common merchants. Changing a category creates a user rule, and the next receipt from that merchant is auto-categorized to match.
- [ ] Every filter in §7 works and combines with the others; search is case-insensitive and supports partial matches.
- [ ] Low-confidence fields are highlighted, and the `needs_review` filter works.
- [ ] Deleting removes both the row and the stored object (tested with moto).
- [ ] Multi-file upload shows progress for each file; one failure doesn't block the others.
- [ ] Reprocessing never overwrites fields listed in `user_edited_fields`.

### Phase 3 — Insights & export
**Stories**
- As a user, I can see monthly spending by category.
- As a user, I can see my spending trend over time.
- As a user, I can set monthly budgets per category and see my progress.
- As a user, I can export receipts to CSV for taxes or expense reports.

**Acceptance criteria**
- [ ] Insights totals match a hand-calculated test dataset exactly (covered by a pytest test).
- [ ] Dashboard charts render correctly with zero, one and many months of data.
- [ ] Budget bars turn amber at the alert threshold and red above 100%.
- [ ] The CSV opens cleanly in Excel and Google Sheets, with one row per receipt and the columns: date, merchant, category, subtotal, tax, tip, total, tags, notes.
- [ ] A Playwright end-to-end test covers: sign up → upload (mock mode) → edit → see it on the dashboard → export.

### Phase 4 — Production-grade (stretch goals)
- **Async pipeline:** an S3 `ObjectCreated` event goes to an SQS queue, which `worker.py` consumes. The API no longer does extraction itself. Include a dead-letter queue and idempotency (skip receipts that are already `ready`).
- **Budget alerts:** email through Amazon SES when spending crosses the alert threshold, at most once per category per month.
- **PDF report:** export a date range as a PDF with a summary table and the receipt images.
- **Infrastructure as code:** AWS CDK (Python) defining the S3 bucket (private, with CORS for presigned uploads and a lifecycle rule), RDS Postgres, the SQS queue and DLQ, App Runner or ECS Fargate for the API and worker, and IAM roles with least privilege (Textract `AnalyzeExpense` plus only the bucket and queue it needs).
- **Deployment:** frontend on Vercel or AWS Amplify; API on App Runner. Secrets live in AWS Secrets Manager or SSM Parameter Store. Add a GitHub Actions deploy workflow.
- **Hardening:** rate limiting on auth and upload endpoints, structured JSON logging, and Sentry (optional).

---

## 10. Engineering Conventions

- **Type everything:** Python type hints throughout (mypy-clean where practical); TypeScript `strict: true`. Keep frontend types in `lib/types.ts` in sync with the Pydantic schemas.
- **Layering:** routers stay thin and business logic lives in `services/`. External calls (S3, Textract, SQS) sit behind small interfaces so they can be mocked.
- **Money:** `Decimal` in Python, `NUMERIC` in Postgres, sent over JSON as strings. Never use floats for money.
- **Dates:** store `purchase_date` as a date; all timestamps in UTC.
- **Never log** passwords, JWTs or full presigned URLs.
- **Tests:** every endpoint gets at least one happy-path test and one auth/ownership test. Run tests against a real Postgres database (docker-compose), not SQLite.
- **Commits:** small and focused, using conventional-commit messages (`feat:`, `fix:`, `test:`, `chore:`).
- **AWS cost safety:** never call real Textract in tests or CI; reprocessing must be an explicit user action; the S3 bucket blocks all public access.

---

## 11. AWS Setup (manual, for Phase 1 real-AWS testing)

Document these steps in the README:
1. Create a private S3 bucket and enable "Block all public access".
2. Add a bucket CORS rule allowing `POST`, `PUT` and `GET` from `http://localhost:3000` (and the production origin later).
3. Create an IAM user or role for local development with a policy allowing `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` on `arn:aws:s3:::BUCKET/users/*`, plus `textract:AnalyzeExpense`.
4. Configure credentials using `aws configure --profile receipt-tracker` and set `AWS_PROFILE`.
5. Set `TEXTRACT_MODE=aws` and `STORAGE_MODE=s3`.
6. Set an AWS Budgets alert (e.g. $5/month) to guard against surprise costs.

---

## 12. Out of Scope (for now)

Bank or card syncing, multi-currency conversion, shared or family accounts, native mobile apps, and email-forwarding ingestion. These are good ideas to add to the README's "Future ideas" section.
