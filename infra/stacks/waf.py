"""WAF web ACL for the CloudFront distribution (us-east-1, CLOUDFRONT scope).

The flat-rate plan requires a web ACL on the distribution (DESIGN.md §10.4). The Free
plan allows 5 rules in total, managed rule groups included; this ACL uses 4.
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

MANAGED_RULE_GROUPS = (
    "AWSManagedRulesCommonRuleSet",
    "AWSManagedRulesAmazonIpReputationList",
    "AWSManagedRulesKnownBadInputsRuleSet",
)


def _visibility(name: str) -> wafv2.CfnWebACL.VisibilityConfigProperty:
    return wafv2.CfnWebACL.VisibilityConfigProperty(
        cloud_watch_metrics_enabled=True, metric_name=name, sampled_requests_enabled=True
    )


class WafStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, rate_limit: int, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        rules = [
            wafv2.CfnWebACL.RuleProperty(
                name="RateLimitPerIp",
                priority=0,
                action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                statement=wafv2.CfnWebACL.StatementProperty(
                    rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                        limit=rate_limit, aggregate_key_type="IP", evaluation_window_sec=300
                    )
                ),
                visibility_config=_visibility("RateLimitPerIp"),
            )
        ]
        for priority, name in enumerate(MANAGED_RULE_GROUPS, start=1):
            rules.append(
                wafv2.CfnWebACL.RuleProperty(
                    name=f"AWS-{name}",
                    priority=priority,
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS", name=name
                        )
                    ),
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    visibility_config=_visibility(name),
                )
            )
        acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            name="takasakiinfo",
            scope="CLOUDFRONT",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=_visibility("takasakiinfo"),
            rules=rules,
        )
        self.web_acl_arn = acl.attr_arn
        CfnOutput(self, "WebAclArn", value=acl.attr_arn)
