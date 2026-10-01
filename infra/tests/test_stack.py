"""Guardrails on the synthesized CloudFormation: privacy, least privilege, the queue wiring."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.stack import MAX_RECEIVE_COUNT, Config, ReceiptTrackerStack

ORIGIN = "https://receipts.example.com"


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App()
    stack = ReceiptTrackerStack(
        app,
        "Test",
        config=Config(
            frontend_origins=[ORIGIN],
            app_base_url=ORIGIN,
            alerts_from_email="alerts@example.com",
            ops_email="ops@example.com",
        ),
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def _resources(template: Template, type_: str) -> dict[str, Any]:
    return template.find_resources(type_)


def _statements_for_role(template: Template, role_prefix: str) -> list[dict[str, Any]]:
    out = []
    for policy in _resources(template, "AWS::IAM::Policy").values():
        roles = [r.get("Ref", "") for r in policy["Properties"].get("Roles", [])]
        if any(r.startswith(role_prefix) for r in roles):
            out.extend(policy["Properties"]["PolicyDocument"]["Statement"])
    return out


def _actions(statements: list[dict[str, Any]]) -> set[str]:
    acts: set[str] = set()
    for st in statements:
        a = st["Action"]
        acts.update(a if isinstance(a, list) else [a])
    return acts


# --- Storage ---------------------------------------------------------------------------------


def test_bucket_is_private_encrypted_and_ssl_only(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.object_like({}),
        },
    )
    template.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_bucket_cors_and_lifecycle(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "CorsConfiguration": {
                "CorsRules": [
                    Match.object_like(
                        {
                            "AllowedOrigins": [ORIGIN],
                            "AllowedMethods": Match.array_with(["POST", "PUT", "GET"]),
                        }
                    )
                ]
            },
            "LifecycleConfiguration": {
                "Rules": Match.array_with(
                    [
                        Match.object_like(
                            {"AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}
                        ),
                        Match.object_like({"Prefix": "users/", "Transitions": Match.any_value()}),
                    ]
                )
            },
        },
    )


def test_uploads_notify_the_queue(template: Template) -> None:
    template.has_resource_properties(
        "Custom::S3BucketNotifications",
        {
            "NotificationConfiguration": {
                "QueueConfigurations": [
                    Match.object_like(
                        {
                            "Events": ["s3:ObjectCreated:*"],
                            "Filter": {
                                "Key": {"FilterRules": [{"Name": "prefix", "Value": "users/"}]}
                            },
                        }
                    )
                ]
            }
        },
    )


def test_queue_has_dlq_and_alarm(template: Template) -> None:
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "VisibilityTimeout": 180,
            "RedrivePolicy": {
                "deadLetterTargetArn": Match.any_value(),
                "maxReceiveCount": MAX_RECEIVE_COUNT,
            },
        },
    )
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"MetricName": "ApproximateNumberOfMessagesVisible", "Threshold": 0},
    )


def test_database_is_isolated_and_encrypted(template: Template) -> None:
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {
            "Engine": "postgres",
            "PubliclyAccessible": False,
            "StorageEncrypted": True,
            "DeletionProtection": True,
            "BackupRetentionPeriod": 7,
        },
    )
    # Only the API and worker security groups may reach Postgres.
    ingress = _resources(template, "AWS::EC2::SecurityGroupIngress")
    assert len(ingress) == 2
    assert all(i["Properties"]["FromPort"] == 5432 for i in ingress.values())


# --- Least privilege ------------------------------------------------------------------------


def test_no_wildcard_actions_anywhere(template: Template) -> None:
    for policy in _resources(template, "AWS::IAM::Policy").values():
        for action in _actions(policy["Properties"]["PolicyDocument"]["Statement"]):
            assert action != "*" and not action.endswith(":*"), action


def test_only_unscopable_actions_use_wildcard_resources(template: Template) -> None:
    allowed = {
        "textract:AnalyzeExpense",  # no resource-level permissions
        "ecr:GetAuthorizationToken",  # account-level by design
        "logs:PutRetentionPolicy",  # CDK's log-retention helper
        "logs:DeleteRetentionPolicy",
    }
    for policy in _resources(template, "AWS::IAM::Policy").values():
        for st in policy["Properties"]["PolicyDocument"]["Statement"]:
            if st["Resource"] == "*":
                assert _actions([st]) <= allowed, st


def test_api_permissions(template: Template) -> None:
    statements = _statements_for_role(template, "ApiInstanceRole")
    assert _actions(statements) == {
        "textract:AnalyzeExpense",
        "ses:SendEmail",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "sqs:SendMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
    }
    s3_statement = next(st for st in statements if "s3:PutObject" in _actions([st]))
    assert "/users/*" in json.dumps(s3_statement["Resource"])


def test_worker_permissions(template: Template) -> None:
    actions = _actions(_statements_for_role(template, "WorkerTaskTaskRole"))
    assert "s3:GetObject" in actions
    assert "sqs:ReceiveMessage" in actions and "sqs:DeleteMessage" in actions
    # The worker never writes or deletes uploads, never enqueues, never reads the JWT key.
    for forbidden in ("s3:PutObject", "s3:DeleteObject", "sqs:SendMessage"):
        assert forbidden not in actions
    secrets = _statements_for_role(template, "WorkerTaskExecutionRole")
    assert "Jwt" not in json.dumps(secrets)


# --- Services -------------------------------------------------------------------------------


def test_api_service_configuration(template: Template) -> None:
    service = next(iter(_resources(template, "AWS::AppRunner::Service").values()))
    image = service["Properties"]["SourceConfiguration"]["ImageRepository"]["ImageConfiguration"]
    env = {kv["Name"]: kv["Value"] for kv in image["RuntimeEnvironmentVariables"]}
    assert env["TEXTRACT_MODE"] == "aws"
    assert env["STORAGE_MODE"] == "s3"
    assert env["COOKIE_SECURE"] == "true"
    assert env["EMAIL_MODE"] == "ses"
    assert env["CORS_ORIGINS"] == ORIGIN
    assert {kv["Name"] for kv in image["RuntimeEnvironmentSecrets"]} == {
        "DATABASE_SECRET",
        "JWT_SECRET",
    }
    # No secret values in plain environment variables.
    assert not any("PASSWORD" in k or k == "JWT_SECRET" for k in env)
    assert service["Properties"]["HealthCheckConfiguration"]["Path"] == "/api/health"
    assert (
        service["Properties"]["NetworkConfiguration"]["EgressConfiguration"]["EgressType"] == "VPC"
    )


def test_worker_service(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Command": ["python", "-m", "app.worker"],
                        "Secrets": [Match.object_like({"Name": "DATABASE_SECRET"})],
                    }
                )
            ]
        },
    )
    template.has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 1, "MaxCapacity": 4}
    )


def test_cost_guardrails(template: Template) -> None:
    template.resource_count_is("AWS::EC2::NatGateway", 1)
    template.has_resource_properties(
        "AWS::Budgets::Budget",
        {"Budget": Match.object_like({"BudgetLimit": {"Amount": 20, "Unit": "USD"}})},
    )
