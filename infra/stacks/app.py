"""Data bucket, API Lambda and the CloudFront distribution (ap-northeast-2). DESIGN.md §10.4, D18.

Routing (3 cache behaviors, managed policies only, so it fits the flat-rate Free plan):

    /          → S3 site/   (connection-map site, §10.7)
    /data/*    → S3 data/   (v1 files, v2 JSON, SQLite, graph.json, version.json)
    /api/*     → Lambda Function URL (read-only queries)

The bucket is private and the Function URL uses AWS_IAM auth; both accept only
requests signed by this distribution through origin access control (OAC).
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

LAMBDA_DIR = Path(__file__).resolve().parent.parent / "lambda"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"


class AppStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        web_acl_arn: str | None,
        github_repo: str,
        deploy_branches: list[str],
        github_oidc_provider_arn: str | None,
        alert_email: str | None,
        budget_usd: float,
        api_reserved_concurrency: int | None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- data bucket ------------------------------------------------------
        bucket = s3.Bucket(
            self,
            "Data",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(90))],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- API Lambda -------------------------------------------------------
        log_group = logs.LogGroup(
            self, "ApiLogs", retention=logs.RetentionDays.ONE_MONTH, removal_policy=RemovalPolicy.DESTROY
        )
        fn = lambda_.Function(
            self,
            "Api",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(LAMBDA_DIR / "api")),
            memory_size=256,
            timeout=Duration.seconds(10),
            reserved_concurrent_executions=api_reserved_concurrency,  # cost guard (§10.4)
            environment={"DATA_BUCKET": bucket.bucket_name, "DATA_PREFIX": "data/"},
            log_group=log_group,
        )
        bucket.grant_read(fn, "data/*")
        fn_url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.AWS_IAM)

        # --- CloudFront -------------------------------------------------------
        site_origin = origins.S3BucketOrigin.with_origin_access_control(bucket, origin_path="/site")
        data_origin = origins.S3BucketOrigin.with_origin_access_control(bucket)
        api_origin = origins.FunctionUrlOrigin.with_origin_access_control(fn_url)
        static = dict(
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            compress=True,
        )
        dist = cloudfront.Distribution(
            self,
            "Cdn",
            comment="TakasakiInfo",
            web_acl_id=web_acl_arn,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(origin=site_origin, **static),
            additional_behaviors={
                "/data/*": cloudfront.BehaviorOptions(
                    origin=data_origin,
                    response_headers_policy=cloudfront.ResponseHeadersPolicy.CORS_ALLOW_ALL_ORIGINS,
                    **static,
                ),
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    # query strings are part of the cache key; TTL comes from the Lambda's Cache-Control
                    cache_policy=cloudfront.CachePolicy.USE_ORIGIN_CACHE_CONTROL_HEADERS_QUERY_STRINGS,
                    # never forward the viewer Host header to the Function URL
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    response_headers_policy=cloudfront.ResponseHeadersPolicy.CORS_ALLOW_ALL_ORIGINS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    compress=True,
                ),
            },
        )
        # FunctionUrlOrigin.with_origin_access_control adds the two Lambda permissions OAC needs
        # (lambda:InvokeFunctionUrl and lambda:InvokeFunction, scoped to this distribution);
        # tests/test_stacks.py asserts they exist.

        # --- GitHub Actions deploy role (data only; no infrastructure rights) --------
        if github_oidc_provider_arn:
            provider_arn = github_oidc_provider_arn
        else:
            provider = iam.OidcProviderNative(
                self, "GitHubOidc", url=GITHUB_OIDC_URL, client_ids=["sts.amazonaws.com"]
            )
            provider_arn = provider.oidc_provider_arn
        role = iam.Role(
            self,
            "DeployRole",
            role_name="takasakiinfo-github-deploy",
            description="GitHub Actions: upload data releases and invalidate the CDN",
            max_session_duration=Duration.hours(1),
            assumed_by=iam.FederatedPrincipal(
                provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{github_repo}:ref:refs/heads/{b}" for b in deploy_branches
                        ],
                    }
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        prefixes = ("releases", "data", "site")
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject", "s3:GetObject"],
            resources=[bucket.arn_for_objects(f"{p}/*") for p in prefixes],
        ))
        role.add_to_policy(iam.PolicyStatement(  # mirror releases into the public prefixes
            actions=["s3:DeleteObject"],
            resources=[bucket.arn_for_objects("data/*"), bucket.arn_for_objects("site/*")],
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:ListBucket"],
            resources=[bucket.bucket_arn],
            conditions={"StringLike": {"s3:prefix": [f"{p}/*" for p in prefixes]}},
        ))
        role.add_to_policy(iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
            resources=[dist.distribution_arn],
        ))

        # --- cost alert -------------------------------------------------------------
        if alert_email:
            subscriber = budgets.CfnBudget.SubscriberProperty(address=alert_email, subscription_type="EMAIL")
            budgets.CfnBudget(
                self,
                "MonthlyBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_name="takasakiinfo-monthly",
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=budget_usd, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            notification_type=kind, comparison_operator="GREATER_THAN",
                            threshold=threshold, threshold_type="PERCENTAGE",
                        ),
                        subscribers=[subscriber],
                    )
                    for kind, threshold in (("ACTUAL", 80), ("FORECASTED", 100))
                ],
            )

        self.distribution_arn = dist.distribution_arn
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=dist.distribution_id)
        CfnOutput(self, "BaseUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "DeployRoleArn", value=role.role_arn)
        CfnOutput(self, "ApiFunctionName", value=fn.function_name)
