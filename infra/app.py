#!/usr/bin/env python3
"""CDK entry point. Settings come from cdk.json context; override with -c key=value."""

import json

import aws_cdk as cdk

from infra.stack import Config, ReceiptTrackerStack


def ctx(app: cdk.App, key: str) -> object:
    value = app.node.try_get_context(key)
    if value is None:
        raise SystemExit(f"Missing CDK context value: {key} (set it in cdk.json or with -c)")
    return value


def as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    text = str(value).strip()
    return json.loads(text) if text.startswith("[") else [v.strip() for v in text.split(",")]


app = cdk.App()
config = Config(
    frontend_origins=as_list(ctx(app, "frontendOrigins")),
    app_base_url=str(ctx(app, "appBaseUrl")),
    alerts_from_email=str(ctx(app, "alertsFromEmail")),
    ops_email=str(ctx(app, "opsEmail")),
    monthly_budget_usd=int(str(app.node.try_get_context("monthlyBudgetUsd") or 20)),
    deletion_protection=str(app.node.try_get_context("deletionProtection") or "true") == "true",
)
ReceiptTrackerStack(
    app,
    str(app.node.try_get_context("stackName") or "ReceiptTracker"),
    config=config,
    # Account/region come from the deploying credentials (CDK_DEFAULT_*).
    env=cdk.Environment(
        account=app.node.try_get_context("account") or None,
        region=app.node.try_get_context("region") or None,
    ),
    description="Receipt Tracker: API, worker, database, uploads and queue",
)
cdk.Tags.of(app).add("app", "receipt-tracker")
app.synth()
