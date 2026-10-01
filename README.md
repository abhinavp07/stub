# Stub

Stub is a receipt scanner and expense tracker. You upload a photo or PDF of a receipt, Amazon
Textract pulls out the merchant, date, totals and line items, and the app files it into a
category. You can fix anything it gets wrong, set monthly budgets, and export to CSV or PDF.

Backend is FastAPI + Postgres, frontend is Next.js. Design notes are in
[DECISIONS.md](DECISIONS.md).

## Running locally

You'll need Docker, [uv](https://docs.astral.sh/uv/), Node 22+ and [pnpm](https://pnpm.io/).

```sh
make setup   # first time: .env, Postgres, dependencies, migrations
make dev     # API on :8000, web app on http://localhost:3000
```

No AWS account is needed for this. By default the app runs in demo mode, where receipt
"extraction" is faked and files are stored in `backend/.uploads/`.

If you don't have `make`:

```sh
cp .env.example .env
docker compose up -d --wait
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && pnpm install && pnpm dev   # in a second terminal
```

### Demo receipts

There are five sample receipts in [`demo-receipts/`](demo-receipts/). Drop them all on the
Upload page:

- `kroger-groceries.png` gets filed under Groceries automatically
- `joes-diner.jpg` has a tip and no matching category rule. Pick one and the next Joe's receipt
  follows it.
- `shell-gas.png` gets filed under Gas
- `starbucks-needs-review.jpg` has a total the OCR wasn't sure about, so it's flagged for review
- `cvs-pharmacy.pdf` is dated last month, so the dashboard has something to compare against

Demo mode recognizes these files and returns their data. It doesn't read images, so any other
file comes back blank for you to fill in (there's a banner in the app saying so). The receipts
are dated in the current month. Run `make demo-receipts` to refresh the dates.

### Reading real receipts

For real receipts, switch on Textract. Locally you only need AWS credentials, no bucket:

1. In IAM, create a user with an access key and a policy allowing `textract:AnalyzeExpense`.
2. `brew install awscli`, then `aws configure --profile stub`
3. In `.env` set `TEXTRACT_MODE=aws` and `AWS_PROFILE=stub`
4. Restart `make dev`

Textract charges about a cent per page. Flat, well-lit photos work best, and PDFs have to be a
single page.

To store uploads in S3 too (`STORAGE_MODE=s3`), you need a private bucket with a CORS rule that
allows `POST`, `PUT` and `GET` from `http://localhost:3000`. Your IAM user also needs
`s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` on `arn:aws:s3:::YOUR_BUCKET/users/*`. Set
`S3_BUCKET` and `AWS_REGION` in `.env`.

## Tests and tooling

```sh
make test     # backend (pytest), frontend (vitest), infra (CDK assertions)
make e2e      # Playwright: sign up, upload, edit, check the dashboard, export
make lint
make format
make migrate
```

Backend tests run against the real Postgres in Docker, not SQLite. The e2e test starts its own
API and web server on ports 8100/3100 with a separate database.

To add a migration after changing a model:

```sh
cd backend && uv run alembic revision --autogenerate -m "what changed"
```

## Project layout

```
backend/     FastAPI app, Alembic migrations, SQS worker (app/worker.py), tests
frontend/    Next.js app; /api/* is proxied to the backend
infra/       AWS CDK stack
demo-receipts/
.github/workflows/   CI on every push, deploy after CI passes on main
```

## Deploying

In production the API runs on App Runner and the database on RDS. Uploads go straight from the
browser to S3. Each upload fires an event onto an SQS queue, and a worker on Fargate picks it up
and calls Textract. Messages that keep failing land in a dead-letter queue, which emails you.
Budget alerts go out through SES. The frontend is meant for Vercel.

All of that is defined in `infra/`. Nothing deploys until you set it up:

1. Bootstrap CDK: `npx aws-cdk@2 bootstrap aws://ACCOUNT_ID/us-east-1`
2. Create a GitHub OIDC identity provider in IAM, plus a role that this repo's `production`
   environment can assume. Let it assume the `cdk-*` bootstrap roles.
3. In the repo settings, add these Actions variables: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`,
   `FRONTEND_ORIGINS`, `APP_BASE_URL`, `ALERTS_FROM_EMAIL`, `OPS_EMAIL`
4. Push to `main` or run the Deploy workflow. To deploy from your machine instead:
   `cd infra && npx aws-cdk@2 deploy -c frontendOrigins=... -c appBaseUrl=... -c alertsFromEmail=... -c opsEmail=...`
5. Click the confirmation links AWS emails you, from SES and SNS. SES only sends to verified
   addresses until you request production access.
6. On Vercel, import the repo with `frontend` as the root directory and set `API_BASE_URL` to
   the `ApiUrl` output from the deploy.

A few things worth knowing:

- Database credentials and the JWT key live in Secrets Manager.
- Migrations run automatically when the API starts.
- To retry messages stuck in the dead-letter queue, use "Start DLQ redrive" in the SQS console.
  It's safe to do, because receipts that are already processed get skipped.
- Expect roughly $60–80 a month at the default sizes, plus Textract. The stack includes a $20
  AWS Budget alert; raise it with `-c monthlyBudgetUsd=...`.
- The database and the uploads bucket survive a `cdk destroy`, on purpose.
