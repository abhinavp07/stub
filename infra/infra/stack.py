"""Stub on AWS.

    S3 (private uploads) --ObjectCreated--> SQS --> worker (ECS Fargate) --> Textract
                                             \\--> DLQ (after 3 failed receives, alarmed)
    browser --> Vercel (Next.js) --/api--> App Runner (FastAPI) --> RDS Postgres (isolated)
                                                         \\--> SES (budget alerts)

Secrets live in Secrets Manager. IAM roles get only what each process calls: the API
presigns uploads (s3:PutObject) and enqueues reprocessing; the worker reads objects for
Textract and consumes the queue. Textract's AnalyzeExpense has no resource-level permissions,
so that one statement is necessarily on "*".
"""

from dataclasses import dataclass, field

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_apprunner as apprunner
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ses as ses
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

RECEIPTS_PREFIX = "users/"
# Long enough for the slowest Textract call plus database work; a message invisible for
# less than its processing time would be handed to a second worker.
VISIBILITY_TIMEOUT = Duration.minutes(3)
MAX_RECEIVE_COUNT = 3


@dataclass
class Config:
    """Deployment settings, read from CDK context (cdk.json or -c key=value)."""

    frontend_origins: list[str]
    app_base_url: str
    alerts_from_email: str
    ops_email: str
    monthly_budget_usd: int = 20
    deletion_protection: bool = True
    api_cpu: str = "0.25 vCPU"
    api_memory: str = "0.5 GB"
    worker_max_tasks: int = 4
    extra_env: dict[str, str] = field(default_factory=dict)


class StubStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: Config, **kwargs: object):
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        c = config

        # --- Network ------------------------------------------------------------------------
        # Public subnets hold the NAT gateway; the API's VPC connector and the worker run in
        # private subnets with egress (AWS APIs); the database is in isolated subnets with no
        # route to the internet at all. One NAT gateway keeps cost down (~$32/month).
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC),
                ec2.SubnetConfiguration(name="app", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                ec2.SubnetConfiguration(name="db", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            ],
        )
        # S3 traffic (Textract reads, worker reads) skips the NAT gateway for free.
        vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
        app_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)

        api_sg = ec2.SecurityGroup(self, "ApiSg", vpc=vpc, description="App Runner VPC connector")
        worker_sg = ec2.SecurityGroup(self, "WorkerSg", vpc=vpc, description="SQS worker tasks")
        db_sg = ec2.SecurityGroup(
            self, "DbSg", vpc=vpc, description="Postgres", allow_all_outbound=False
        )
        for sg, who in ((api_sg, "API"), (worker_sg, "worker")):
            db_sg.add_ingress_rule(sg, ec2.Port.tcp(5432), f"Postgres from the {who}")

        # --- Database -----------------------------------------------------------------------
        db = rds.DatabaseInstance(
            self,
            "Db",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_sg],
            credentials=rds.Credentials.from_generated_secret("receipts"),
            database_name="receipts",
            allocated_storage=20,
            max_allocated_storage=100,
            storage_encrypted=True,
            publicly_accessible=False,
            multi_az=False,
            backup_retention=Duration.days(7),
            deletion_protection=c.deletion_protection,
            removal_policy=RemovalPolicy.SNAPSHOT,
            cloudwatch_logs_exports=["postgresql"],
            cloudwatch_logs_retention=logs.RetentionDays.ONE_MONTH,
        )
        assert db.secret is not None
        db_secret = db.secret

        jwt_secret = secretsmanager.Secret(
            self,
            "JwtSecret",
            description="Signing key for session JWTs",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=64, exclude_punctuation=True
            ),
        )

        # --- Uploads bucket -----------------------------------------------------------------
        bucket = s3.Bucket(
            self,
            "Uploads",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=RemovalPolicy.RETAIN,
            cors=[
                # The browser uploads straight to S3 with a presigned POST, and shows images
                # from presigned GET URLs.
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.POST, s3.HttpMethods.PUT, s3.HttpMethods.GET],
                    allowed_origins=c.frontend_origins,
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="abort-incomplete-uploads",
                    abort_incomplete_multipart_upload_after=Duration.days(1),
                ),
                s3.LifecycleRule(
                    id="older-receipts-to-infrequent-access",
                    prefix=RECEIPTS_PREFIX,
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(90),
                        )
                    ],
                ),
            ],
        )

        # --- Queue --------------------------------------------------------------------------
        dlq = sqs.Queue(
            self,
            "ReceiptsDlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
        )
        queue = sqs.Queue(
            self,
            "ReceiptsQueue",
            visibility_timeout=VISIBILITY_TIMEOUT,
            retention_period=Duration.days(4),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=MAX_RECEIVE_COUNT),
        )
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.SqsDestination(queue),
            s3.NotificationKeyFilter(prefix=RECEIPTS_PREFIX),
        )

        # --- Email & alarms -----------------------------------------------------------------
        # SES starts in the sandbox: until production access is granted, it only delivers
        # to verified addresses (see README).
        sender_identity = ses.EmailIdentity(
            self, "AlertsSender", identity=ses.Identity.email(c.alerts_from_email)
        )
        sender_arn = self.format_arn(
            service="ses", resource="identity", resource_name=c.alerts_from_email
        )

        ops_topic = sns.Topic(self, "OpsAlerts", display_name="Stub alerts")
        ops_topic.add_subscription(subs.EmailSubscription(c.ops_email))
        dlq_alarm = cloudwatch.Alarm(
            self,
            "DlqNotEmpty",
            alarm_description="Receipt messages failed repeatedly and landed in the DLQ",
            metric=dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(5), statistic="Maximum"
            ),
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        dlq_alarm.add_alarm_action(cw_actions.SnsAction(ops_topic))

        budgets.CfnBudget(
            self,
            "CostBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=c.monthly_budget_usd, unit="USD"
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind,
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL", address=c.ops_email
                        )
                    ],
                )
                for kind in ("ACTUAL", "FORECASTED")
            ],
        )

        # --- Shared image & configuration ---------------------------------------------------
        image = ecr_assets.DockerImageAsset(
            self,
            "BackendImage",
            directory="../backend",
            platform=ecr_assets.Platform.LINUX_AMD64,
        )
        env = {
            "AWS_REGION": self.region,
            "TEXTRACT_MODE": "aws",
            "STORAGE_MODE": "s3",
            "S3_BUCKET": bucket.bucket_name,
            "SQS_QUEUE_URL": queue.queue_url,
            "EMAIL_MODE": "ses",
            "EMAIL_FROM": f"Stub <{c.alerts_from_email}>",
            "APP_BASE_URL": c.app_base_url,
            "CORS_ORIGINS": ",".join(c.frontend_origins),
            "COOKIE_SECURE": "true",
            "LOG_FORMAT": "json",
            # Browser -> Vercel (adds the client IP) -> App Runner (adds Vercel's IP).
            "TRUSTED_PROXY_HOPS": "2",
            **c.extra_env,
        }

        textract = iam.PolicyStatement(actions=["textract:AnalyzeExpense"], resources=["*"])
        send_email = iam.PolicyStatement(actions=["ses:SendEmail"], resources=[sender_arn])
        receipt_objects = bucket.arn_for_objects(f"{RECEIPTS_PREFIX}*")

        # --- API: App Runner ----------------------------------------------------------------
        api_role = iam.Role(
            self,
            "ApiInstanceRole",
            assumed_by=iam.ServicePrincipal("tasks.apprunner.amazonaws.com"),
            description="Runtime permissions for the API",
        )
        api_role.add_to_policy(textract)
        api_role.add_to_policy(send_email)
        api_role.add_to_policy(
            iam.PolicyStatement(
                # PutObject: presigned upload POSTs are authorized as this role.
                # GetObject: presigned image URLs and HeadObject. DeleteObject: receipt delete.
                actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
                resources=[receipt_objects],
            )
        )
        queue.grant_send_messages(api_role)  # reprocess requests
        db_secret.grant_read(api_role)
        jwt_secret.grant_read(api_role)

        access_role = iam.Role(
            self,
            "ApiAccessRole",
            assumed_by=iam.ServicePrincipal("build.apprunner.amazonaws.com"),
            description="Lets App Runner pull the API image",
        )
        image.repository.grant_pull(access_role)

        connector = apprunner.CfnVpcConnector(
            self,
            "ApiVpcConnector",
            subnets=vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS).subnet_ids,
            security_groups=[api_sg.security_group_id],
        )
        api = apprunner.CfnService(
            self,
            "Api",
            source_configuration=apprunner.CfnService.SourceConfigurationProperty(
                auto_deployments_enabled=False,
                authentication_configuration=apprunner.CfnService.AuthenticationConfigurationProperty(
                    access_role_arn=access_role.role_arn
                ),
                image_repository=apprunner.CfnService.ImageRepositoryProperty(
                    image_identifier=image.image_uri,
                    image_repository_type="ECR",
                    image_configuration=apprunner.CfnService.ImageConfigurationProperty(
                        port="8000",
                        runtime_environment_variables=[
                            apprunner.CfnService.KeyValuePairProperty(name=k, value=v)
                            for k, v in sorted(env.items())
                        ],
                        runtime_environment_secrets=[
                            apprunner.CfnService.KeyValuePairProperty(
                                name="DATABASE_SECRET", value=db_secret.secret_arn
                            ),
                            apprunner.CfnService.KeyValuePairProperty(
                                name="JWT_SECRET", value=jwt_secret.secret_arn
                            ),
                        ],
                    ),
                ),
            ),
            instance_configuration=apprunner.CfnService.InstanceConfigurationProperty(
                cpu=c.api_cpu, memory=c.api_memory, instance_role_arn=api_role.role_arn
            ),
            health_check_configuration=apprunner.CfnService.HealthCheckConfigurationProperty(
                protocol="HTTP", path="/api/health", interval=10, healthy_threshold=1
            ),
            network_configuration=apprunner.CfnService.NetworkConfigurationProperty(
                egress_configuration=apprunner.CfnService.EgressConfigurationProperty(
                    egress_type="VPC", vpc_connector_arn=connector.attr_vpc_connector_arn
                )
            ),
        )
        api.node.add_dependency(api_role, access_role)

        # --- Worker: ECS Fargate ------------------------------------------------------------
        cluster = ecs.Cluster(
            self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED
        )
        task = ecs.FargateTaskDefinition(
            self,
            "WorkerTask",
            cpu=256,
            memory_limit_mib=512,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        task.add_container(
            "worker",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            command=["python", "-m", "app.worker"],
            environment=env,
            secrets={"DATABASE_SECRET": ecs.Secret.from_secrets_manager(db_secret)},
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="worker", log_retention=logs.RetentionDays.ONE_MONTH
            ),
            stop_timeout=Duration.seconds(60),  # let in-flight messages finish on SIGTERM
        )
        task.add_to_task_role_policy(textract)
        task.add_to_task_role_policy(send_email)
        # Textract reads the object with the caller's permissions.
        task.add_to_task_role_policy(
            iam.PolicyStatement(actions=["s3:GetObject"], resources=[receipt_objects])
        )
        queue.grant_consume_messages(task.task_role)

        worker = ecs.FargateService(
            self,
            "Worker",
            cluster=cluster,
            task_definition=task,
            desired_count=1,
            vpc_subnets=app_subnets,
            security_groups=[worker_sg],
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
        )
        scaling = worker.auto_scale_task_count(min_capacity=1, max_capacity=c.worker_max_tasks)
        scaling.scale_on_metric(
            "QueueDepth",
            metric=queue.metric_approximate_number_of_messages_visible(period=Duration.minutes(1)),
            # Drop a task when the queue is nearly empty; add tasks as a backlog builds.
            scaling_steps=[
                appscaling.ScalingInterval(upper=5, change=-1),
                appscaling.ScalingInterval(lower=10, change=+1),
                appscaling.ScalingInterval(lower=50, change=+3),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        )

        # --- Outputs ------------------------------------------------------------------------
        CfnOutput(self, "ApiUrl", value=f"https://{api.attr_service_url}")
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "QueueUrl", value=queue.queue_url)
        CfnOutput(self, "DeadLetterQueueUrl", value=dlq.queue_url)
        CfnOutput(self, "SesIdentity", value=sender_identity.email_identity_name)

        self.bucket, self.queue, self.dlq, self.db = bucket, queue, dlq, db
        self.api_role, self.worker_role = api_role, task.task_role
