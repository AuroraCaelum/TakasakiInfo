"""Stack wiring shared by app.py and the tests."""

from dataclasses import dataclass

import aws_cdk as cdk

from .app import AppStack
from .plan import PlanStack
from .waf import WafStack


@dataclass
class Stacks:
    waf: WafStack | None
    app: AppStack
    plan: PlanStack | None


def _flag(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).lower() not in ("false", "0", "no", "off")


def build(app: cdk.App, account: str) -> Stacks:
    ctx = app.node.try_get_context
    edge = cdk.Environment(account=account, region="us-east-1")
    home = cdk.Environment(account=account, region=ctx("app_region") or "ap-northeast-2")
    # flat_rate=false: plain pay-as-you-go distribution without WAF. A web ACL outside a plan is
    # billed (~$8/month), so it only exists together with the Free plan subscription.
    flat_rate = _flag(ctx("flat_rate"), True)
    waf = (
        WafStack(app, "TakasakiInfo-Waf", env=edge, cross_region_references=True,
                 rate_limit=int(ctx("waf_rate_limit") or 1000))
        if flat_rate else None
    )
    reserved = int(ctx("api_reserved_concurrency") if ctx("api_reserved_concurrency") is not None else 5)
    main = AppStack(
        app,
        "TakasakiInfo-App",
        env=home,
        cross_region_references=True,
        web_acl_arn=waf.web_acl_arn if waf else None,
        github_repo=ctx("github_repo") or "AuroraCaelum/TakasakiInfo",
        deploy_branches=list(ctx("deploy_branches") or ["main"]),
        github_oidc_provider_arn=ctx("github_oidc_provider_arn") or None,
        alert_email=ctx("alert_email") or None,
        budget_usd=float(ctx("budget_usd") or 1),
        api_reserved_concurrency=reserved or None,  # 0 = no reservation (accounts with a low quota)
    )
    # the plan needs both ARNs; references order the deploys: Waf → App → Plan
    plan = (
        PlanStack(app, "TakasakiInfo-Plan", env=edge, cross_region_references=True,
                  distribution_arn=main.distribution_arn, web_acl_arn=waf.web_acl_arn)
        if waf else None
    )
    for stack in (waf, main, plan):
        if stack:
            cdk.Tags.of(stack).add("project", "takasakiinfo")
    return Stacks(waf, main, plan)
