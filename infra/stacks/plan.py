"""CloudFront flat-rate Free plan subscription (DESIGN.md D21).

PricingPlanManager is served from us-east-1 only, and the subscription needs the
distribution and the web ACL to exist first: web ACL → distribution → subscription.
Free plans activate immediately (no approval step, no charge).
"""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_pricingplanmanager as ppm
from constructs import Construct


class PlanStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, distribution_arn: str, web_acl_arn: str,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        sub = ppm.CfnSubscription(
            self,
            "FlatRatePlan",
            plan_family="CloudFront",
            plan_tier="FREE",
            resource_arns=[distribution_arn, web_acl_arn],
        )
        CfnOutput(self, "SubscriptionArn", value=sub.ref)
