#!/usr/bin/env python3
"""CDK app: three stacks wired with cross-region references (DESIGN.md §10.4, D21–D22).

    TakasakiInfo-Waf   us-east-1       WAF web ACL (CLOUDFRONT scope must live in us-east-1)
    TakasakiInfo-App   ap-northeast-2  S3, Lambda + Function URL, CloudFront, deploy role, budget
    TakasakiInfo-Plan  us-east-1       flat-rate Free subscription (PricingPlanManager is us-east-1 only)

Context (cdk.json or -c key=value):
    account                   AWS account id (required; or CDK_DEFAULT_ACCOUNT)
    alert_email               budget alert address (optional)
    github_oidc_provider_arn  existing GitHub OIDC provider ARN, if the account already has one
    deploy_branches           branches allowed to assume the deploy role
"""

import os

import aws_cdk as cdk

from stacks import build

app = cdk.App()
account = app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
if not account:
    raise SystemExit("set the AWS account: cdk ... -c account=123456789012 (or log in so CDK_DEFAULT_ACCOUNT is set)")
build(app, account)
app.synth()
