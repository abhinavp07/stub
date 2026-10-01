# Receipt Tracker

Upload photos or PDFs of receipts. The app extracts merchant, date, totals and line items with
Amazon Textract (`AnalyzeExpense`), categorizes them, and shows spending insights. You can review
and correct anything the extraction gets wrong.

See [SPEC.md](SPEC.md) for the full specification and [DECISIONS.md](DECISIONS.md) for choices
made along the way.

## Run it locally

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22+ and
[pnpm](https://pnpm.io/). No AWS credentials are needed: by default `TEXTRACT_MODE=mock` and
`STORAGE_MODE=local`.

```sh
make setup   # creates .env, starts Postgres, installs deps, runs migrations
make dev     # API on http://localhost:8000, web on http://localhost:3000
```

Open http://localhost:3000, sign up, and upload any JPG, PNG or PDF. In mock mode the "extraction"
returns one of three realistic sample receipts (grocery, restaurant, gas station) after a short
delay, so you can try the whole flow offline.

<details>
<summary>Without make</summary>

```sh
cp .env.example .env && docker compose up -d --wait
cd backend && uv sync && uv run alembic upgrade head && cd ..
cd backend && uv run uvicorn app.main:app --reload       # terminal 1
cd frontend && pnpm install && pnpm dev                  # terminal 2
```

</details>

## Layout

| Path | What |
|---|---|
| `backend/` | FastAPI (Python 3.12), SQLAlchemy 2 async, Alembic migrations, pytest |
| `frontend/` | Next.js 15 App Router, TypeScript, Tailwind, Vitest. `/api/*` is proxied to FastAPI |
| `docker-compose.yml` | Postgres 16 (also creates a `receipts_test` database for tests) |
| `.github/workflows/ci.yml` | Lint, migrations check, and tests for both apps |

## Common tasks

```sh
make test      # backend pytest + frontend vitest
make lint      # ruff, eslint, prettier, tsc
make format    # auto-fix formatting
make migrate   # alembic upgrade head

# New migration after changing models:
cd backend && uv run alembic revision --autogenerate -m "describe change"
```

## Using real AWS (Textract + S3)

Local development never needs AWS. To test real extraction:

1. Create a private S3 bucket (e.g. `receipt-tracker-dev-uploads`) and keep **Block all public
   access** on.
2. Add a CORS rule to the bucket so the browser can upload directly:
   ```json
   [
     {
       "AllowedOrigins": ["http://localhost:3000"],
       "AllowedMethods": ["POST", "PUT", "GET"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 3000
     }
   ]
   ```
   Add your production origin here later.
3. Create an IAM user or role for local development with this policy (replace `BUCKET`):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
         "Resource": "arn:aws:s3:::BUCKET/users/*"
       },
       { "Effect": "Allow", "Action": "textract:AnalyzeExpense", "Resource": "*" }
     ]
   }
   ```
4. Configure credentials: `aws configure --profile receipt-tracker`, then add
   `AWS_PROFILE=receipt-tracker` to `.env`.
5. In `.env`, set `TEXTRACT_MODE=aws`, `STORAGE_MODE=s3`, `S3_BUCKET=<your bucket>` and
   `AWS_REGION=<bucket region>`. Restart the API.
6. Set an AWS Budgets alert (e.g. $5/month) to guard against surprise costs. AnalyzeExpense is
   billed per page.

You can also mix modes: `TEXTRACT_MODE=aws` with `STORAGE_MODE=local` sends the file bytes to
Textract directly, so you don't need a bucket to try real extraction.

### Verifying real extraction by hand

1. With the settings above, `make dev`, sign up, and upload a photo of a real receipt.
2. The detail page shows **Processing** and then switches to **Ready** on its own (it polls every
   2 seconds).
3. Check that merchant, date, subtotal, tax, total and line items match the paper receipt.
   Fields Textract was unsure of have an amber outline; hover one to see its confidence.
4. In the S3 console, confirm the object exists at `users/<user id>/receipts/<receipt id>.<ext>`.
5. Delete the receipt and confirm the S3 object is gone.

Limits: synchronous AnalyzeExpense reads single-page PDFs only. A multi-page PDF fails with a
message asking for a photo or single-page PDF.

## Future ideas

Out of scope for now: bank or card syncing, multi-currency conversion, shared or family accounts,
native mobile apps, and email-forwarding ingestion.
