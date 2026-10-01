# Stub

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

Open http://localhost:3000, sign up, and upload receipts. In mock mode the "extraction" returns
realistic sample data after a short delay, so the whole flow works offline.

### Demo receipts

[`demo-receipts/`](demo-receipts/) has five receipts to try. Drag them all onto the Upload page at
once:

| File | What it shows |
|---|---|
| `kroger-groceries.png` | Line items, quantities, auto-filed under Groceries |
| `joes-diner.jpg` | A tip; no rule matches, so pick a category and the next one follows |
| `shell-gas.png` | Fuel priced per gallon, auto-filed under Gas |
| `starbucks-needs-review.jpg` | A low-confidence total: amber outline and a "Needs review" flag |
| `cvs-pharmacy.pdf` | A PDF receipt, dated last month (for the month-over-month comparison) |

In mock mode each demo file extracts as itself, with the date printed on it. **Mock mode never
reads images**, so any other file comes back blank and flagged for review (an amber banner in the
app says so). To read your own receipts, see below. The dates are in the current month so the dashboard has data;
`make demo-receipts` regenerates them with fresh dates. With `TEXTRACT_MODE=aws`, Textract reads
the same values off the images. Kroger and Shell receipts are filed automatically
(Groceries, Gas); move a Joe's Diner receipt into a category and the next one follows. The
dashboard shows this month vs last, spending by category, a 12-month trend and budget
progress; Export CSV is on the dashboard and the receipts list.

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
| `.github/workflows/ci.yml` | Lint, migrations check, unit tests for both apps, then the Playwright e2e |
| `frontend/e2e/` | Playwright end-to-end test (runs against its own `receipts_e2e` database) |
| `backend/app/worker.py` | SQS consumer that runs extraction in production |
| `infra/` | AWS CDK (Python): VPC, RDS, S3, SQS + DLQ, App Runner, Fargate worker, SES, IAM |
| `.github/workflows/deploy.yml` | Deploys the stack after CI passes on `main` (once AWS is configured) |

## Common tasks

```sh
make test      # backend pytest + frontend vitest
make e2e       # Playwright: sign up → upload → edit → dashboard → export
make lint      # ruff, eslint, prettier, tsc
make format    # auto-fix formatting
make migrate   # alembic upgrade head
make demo-receipts  # refresh demo-receipts/ with this month's dates

# New migration after changing models:
cd backend && uv run alembic revision --autogenerate -m "describe change"
```

### Reading real receipts

Real extraction uses Amazon Textract. Locally you only need AWS credentials, not a bucket:

1. In the AWS console (IAM), create a user with an access key and attach a policy allowing
   `textract:AnalyzeExpense`.
2. `brew install awscli && aws configure --profile stub` (enter the key; region `us-east-1`).
3. Create `.env` if you haven't (`cp .env.example .env`) and set:
   ```
   TEXTRACT_MODE=aws
   AWS_PROFILE=stub
   ```
   Leave `STORAGE_MODE=local`; files are sent to Textract directly.
4. Restart `make dev`. The demo-mode banner disappears, and uploads are read for real.

AnalyzeExpense costs about $0.01 per page (check current Textract pricing). Photos work best flat,
well lit and filling the frame. Sync AnalyzeExpense reads single-page PDFs only.

## Using real AWS (Textract + S3)

Local development never needs AWS. To test real extraction:

1. Create a private S3 bucket (e.g. `stub-dev-uploads`) and keep **Block all public
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
4. Configure credentials: `aws configure --profile stub`, then add
   `AWS_PROFILE=stub` to `.env`.
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

## Deploying to AWS

Production runs the same code with the AWS paths switched on:

```
browser ──▶ Vercel (Next.js) ──/api──▶ App Runner (FastAPI) ──▶ RDS Postgres (private)
   │                                        │  └─▶ SES (budget alert emails)
   └── presigned POST ──▶ S3 (private) ──ObjectCreated──▶ SQS ──▶ worker (Fargate) ──▶ Textract
                                                          └─▶ DLQ after 3 failures (alarm)
```

Everything except the frontend is defined in [`infra/`](infra/) with the AWS CDK (Python).
`cd infra && uv run pytest` checks the template's guardrails (private bucket, least-privilege
IAM, DLQ wiring) without AWS credentials.

### One-time setup

1. **Bootstrap CDK** in the target account and region:
   `npx aws-cdk@2 bootstrap aws://ACCOUNT_ID/us-east-1`
2. **Allow GitHub to deploy** without stored keys: create an IAM OIDC identity provider for
   `token.actions.githubusercontent.com`, and a role it can assume, restricted to this repo's
   `main` branch (`repo:abhinavp07/stub:environment:production`). Give the role permission to
   assume the CDK bootstrap roles (`cdk-*-deploy-role-*`, `cdk-*-file-publishing-role-*`,
   `cdk-*-image-publishing-role-*`, `cdk-*-lookup-role-*`).
3. **Set repository variables** (Settings → Secrets and variables → Actions → Variables):
   `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `FRONTEND_ORIGINS` (e.g.
   `https://your-app.vercel.app`), `APP_BASE_URL` (same), `ALERTS_FROM_EMAIL`, `OPS_EMAIL`.
   Create a `production` environment if you want a manual approval step before each deploy.
4. **Deploy.** Push to `main` (deploys after CI passes) or run the *Deploy* workflow by hand. To
   deploy from your machine instead: `cd infra && npx aws-cdk@2 deploy -c frontendOrigins=... -c
   appBaseUrl=... -c alertsFromEmail=... -c opsEmail=...`. The `ApiUrl` output is the App Runner
   URL.
5. **Confirm the emails AWS sends you:** SES verifies `ALERTS_FROM_EMAIL`, and SNS confirms the
   `OPS_EMAIL` subscription for DLQ and cost alarms.
6. **SES sandbox:** new accounts can only send to verified addresses. Request production access
   in the SES console before real users get budget alerts.
7. **Frontend on Vercel:** import the repo with root directory `frontend` and set
   `API_BASE_URL` to the `ApiUrl` output. Next.js proxies `/api/*` there, so the browser stays on
   one origin and the auth cookie just works.

### Operating it

- **Secrets** (database credentials, JWT key) are generated into Secrets Manager and injected at
  runtime; none are in the image, the template outputs or GitHub.
- **Migrations** run when an API instance starts, and a Postgres advisory lock serializes
  instances that start together.
- **Failed messages** land in the dead-letter queue after 3 attempts, and `OPS_EMAIL` gets an
  alarm. Once the cause is fixed, redrive them from the SQS console ("Start DLQ redrive"). The
  worker skips receipts that are already `ready`, so redriving is safe.
- **Logs** are JSON in CloudWatch (App Runner and `/ecs` log groups).
- **Cost:** with the defaults (db.t4g.micro, one NAT gateway, one Fargate task, the smallest App
  Runner instance) expect roughly $60–80/month before Textract, which bills per page. The stack
  includes a $20/month AWS Budget that emails `OPS_EMAIL` at 80% (raise it with
  `-c monthlyBudgetUsd=`).
- **Tearing down:** the database has deletion protection and is snapshotted on delete, and the
  uploads bucket is retained. Both are deliberate.

## Future ideas

Out of scope for now: bank or card syncing, multi-currency conversion, shared or family accounts,
native mobile apps, and email-forwarding ingestion.
