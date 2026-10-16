"""Pin the settings that matter for security, cost and the flat-rate plan (DESIGN.md §10.4)."""

import json

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from stacks import build

# AWS managed policy ids (stable across accounts)
CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"
ORIGIN_CACHE_CONTROL_QS = "4cc15a8a-d715-48a4-82b8-cc0b614638fe"
ALL_VIEWER_EXCEPT_HOST = "b689b0a8-53d0-40ab-baf2-68738e2966ac"


@pytest.fixture(scope="module")
def templates():
    app = cdk.App(context={
        "deploy_branches": ["main"],
        "alert_email": "alerts@example.com",
        "@aws-cdk/core:defaultCrossStackReferences": "strong",
    })
    s = build(app, "111111111111")
    return Template.from_stack(s.waf), Template.from_stack(s.app), Template.from_stack(s.plan)


def _resources(t: Template, typ: str) -> list[dict]:
    return list(t.find_resources(typ).values())


def test_bucket_is_private(templates):
    _, app, _ = templates
    app.has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        },
        "VersioningConfiguration": {"Status": "Enabled"},
    })
    statements = [s for p in _resources(app, "AWS::S3::BucketPolicy") for s in p["Properties"]["PolicyDocument"]["Statement"]]
    allows = [s for s in statements if s["Effect"] == "Allow"]
    assert allows and all(s["Principal"] == {"Service": "cloudfront.amazonaws.com"} for s in allows)
    assert all("AWS:SourceArn" in json.dumps(s["Condition"]) for s in allows)


def test_function_url_only_through_cloudfront(templates):
    _, app, _ = templates
    app.has_resource_properties("AWS::Lambda::Url", {"AuthType": "AWS_IAM"})
    perms = [p["Properties"] for p in _resources(app, "AWS::Lambda::Permission")]
    assert sorted(p["Action"] for p in perms) == ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"]
    assert all(p["Principal"] == "cloudfront.amazonaws.com" and "distribution/" in json.dumps(p["SourceArn"])
               for p in perms)
    app.has_resource_properties("AWS::Lambda::Function", {"ReservedConcurrentExecutions": 5})


def test_distribution_routes_and_flat_rate_constraints(templates):
    _, app, _ = templates
    (dist,) = _resources(app, "AWS::CloudFront::Distribution")
    cfg = dist["Properties"]["DistributionConfig"]
    assert "WebACLId" in cfg
    behaviors = {b["PathPattern"]: b for b in cfg["CacheBehaviors"]}
    assert set(behaviors) == {"/data/*", "/api/*"}  # 3 behaviors with the default; Free plan allows 5
    assert cfg["DefaultCacheBehavior"]["CachePolicyId"] == CACHING_OPTIMIZED
    assert behaviors["/data/*"]["CachePolicyId"] == CACHING_OPTIMIZED
    api = behaviors["/api/*"]
    assert api["CachePolicyId"] == ORIGIN_CACHE_CONTROL_QS
    assert api["OriginRequestPolicyId"] == ALL_VIEWER_EXCEPT_HOST
    assert api["AllowedMethods"] == ["GET", "HEAD"]
    text = json.dumps(cfg)
    assert "ForwardedValues" not in text and "OriginAccessIdentity\": \"origin-access-identity" not in text
    assert all(o.get("OriginAccessControlId") for o in cfg["Origins"])
    # the site origin must not expose the bucket root (releases/ stays unreachable)
    assert {o.get("OriginPath") for o in cfg["Origins"]} == {"/site", None}
    oac_types = sorted(p["Properties"]["OriginAccessControlConfig"]["OriginAccessControlOriginType"]
                       for p in _resources(app, "AWS::CloudFront::OriginAccessControl"))
    assert "lambda" in oac_types and "s3" in oac_types


def test_deploy_role_is_scoped(templates):
    _, app, _ = templates
    roles = [r for r in _resources(app, "AWS::IAM::Role") if "Federated" in json.dumps(r["Properties"]["AssumeRolePolicyDocument"])]
    (role,) = roles
    cond = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"]
    assert cond["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    assert cond["token.actions.githubusercontent.com:sub"] in (
        "repo:AuroraCaelum/TakasakiInfo:ref:refs/heads/main", ["repo:AuroraCaelum/TakasakiInfo:ref:refs/heads/main"])
    actions = {a for p in _resources(app, "AWS::IAM::Policy")
               for s in p["Properties"]["PolicyDocument"]["Statement"]
               for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert "*" not in actions and not any(a.endswith(":*") for a in actions)
    assert {"s3:PutObject", "cloudfront:CreateInvalidation"} <= actions


def test_budget_alert(templates):
    _, app, _ = templates
    app.has_resource_properties("AWS::Budgets::Budget", {
        "Budget": Match.object_like({"BudgetLimit": {"Amount": 1, "Unit": "USD"}, "TimeUnit": "MONTHLY"}),
    })


def test_waf_fits_the_free_plan(templates):
    waf, _, _ = templates
    (acl,) = _resources(waf, "AWS::WAFv2::WebACL")
    assert acl["Properties"]["Scope"] == "CLOUDFRONT"
    assert len(acl["Properties"]["Rules"]) <= 5


def test_plan_is_free_tier(templates):
    _, _, plan = templates
    plan.has_resource_properties("AWS::PricingPlanManager::Subscription", {
        "PlanFamily": "CloudFront", "PlanTier": "FREE",
    })


def test_without_flat_rate_there_is_no_waf():
    app = cdk.App(context={"flat_rate": "false", "api_reserved_concurrency": "0",
                           "@aws-cdk/core:defaultCrossStackReferences": "strong"})
    s = build(app, "111111111111")
    assert s.waf is None and s.plan is None
    t = Template.from_stack(s.app)
    (dist,) = _resources(t, "AWS::CloudFront::Distribution")
    assert "WebACLId" not in dist["Properties"]["DistributionConfig"]
    (fn,) = [f for f in _resources(t, "AWS::Lambda::Function") if f["Properties"].get("Handler") == "handler.handler"]
    assert "ReservedConcurrentExecutions" not in fn["Properties"]
