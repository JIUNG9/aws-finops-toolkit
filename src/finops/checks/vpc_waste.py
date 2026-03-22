"""VPC Waste Detection — Find abandoned VPCs and their hidden cost drivers.

Based on real-world FinOps work finding entire abandoned VPCs costing
$525-748/month. The pattern: a VPC is created for a project, the project
ends, but nobody deletes the VPC. The NAT Gateways, Elastic IPs, VPC
endpoints, WorkSpaces, and Directory Services keep running silently.

This check scans for:
  1. VPCs with no running EC2/EKS instances but still paying for NAT GWs, EIPs
  2. VPCs with only stopped/terminated instances
  3. NAT Gateways with zero data processed over 14 days
  4. VPC endpoints that haven't been used
  5. WorkSpaces in STOPPED or UNHEALTHY state for 30+ days
  6. Directory Services with no active WorkSpaces
  7. Storage Gateways with no recent activity

Typical savings: $525-748/month per abandoned VPC.

AWS APIs used:
  - ec2:DescribeVpcs
  - ec2:DescribeInstances
  - ec2:DescribeNatGateways
  - ec2:DescribeAddresses
  - ec2:DescribeVpcEndpoints
  - cloudwatch:GetMetricStatistics
  - workspaces:DescribeWorkspaces
  - workspaces:DescribeWorkspaceDirectories
  - storagegateway:ListGateways
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finops.checks.base import BaseCheck, CheckResult


# --- Pricing Constants (us-east-1, monthly) ---

# NAT Gateway: $0.045/hr * 730 hrs = ~$32.85, but commonly rounded to $43/mo
# when including typical data processing charges
NAT_GATEWAY_MONTHLY_COST = 43.00     # $/month (fixed + avg data processing)
NAT_GATEWAY_FIXED_MONTHLY = 32.85    # $/month (fixed only, $0.045/hr * 730)

# Elastic IP: $0.005/hr * 730 hrs = $3.65/month
EIP_MONTHLY_COST = 3.65              # $/month

# VPC Endpoints (Interface type): $0.01/hr * 730 hrs per AZ
VPC_ENDPOINT_PER_AZ_MONTHLY = 7.30   # $/month per AZ

# WorkSpaces pricing (common bundles, monthly)
WORKSPACES_BUNDLE_COSTS: dict[str, float] = {
    "Value": 25.00,
    "Standard": 35.00,
    "Performance": 60.00,
    "Power": 80.00,
    "PowerPro": 124.00,
    "GraphicsPro": 502.00,
    "Graphics.g4dn": 466.00,
}
WORKSPACES_DEFAULT_COST = 35.00      # Fallback if bundle unknown

# Directory Service monthly costs
DIRECTORY_SIMPLE_AD_MONTHLY = 144.00       # Small: $72, Large: $144
DIRECTORY_MICROSOFT_AD_MONTHLY = 360.00    # Standard: $144, Enterprise: $360
DIRECTORY_AD_CONNECTOR_MONTHLY = 72.00     # Small: $36, Large: $72

DIRECTORY_COSTS: dict[str, float] = {
    "SimpleAD": DIRECTORY_SIMPLE_AD_MONTHLY,
    "MicrosoftAD": DIRECTORY_MICROSOFT_AD_MONTHLY,
    "ADConnector": DIRECTORY_AD_CONNECTOR_MONTHLY,
}

# Storage Gateway (base cost when idle)
STORAGE_GATEWAY_MONTHLY_BASE = 125.00  # Approximate base cost (varies by type)


class VPCWasteCheck(BaseCheck):
    """Detect abandoned VPCs and related resources still incurring charges.

    Scans for VPCs with no running workloads that are still paying for
    NAT Gateways, EIPs, endpoints, WorkSpaces, and Directory Services.
    """

    name = "vpc_waste"
    description = "Find abandoned VPCs costing $525-748/mo with no running workloads"

    def run(self, session: Any, region: str) -> list[CheckResult]:
        """Execute all VPC waste sub-checks.

        Args:
            session: Authenticated boto3.Session.
            region: AWS region to scan.

        Returns:
            Combined list of CheckResult from all sub-checks.
        """
        results: list[CheckResult] = []

        results.extend(self._check_abandoned_vpcs(session, region))
        results.extend(self._check_idle_nat_gateways(session, region))
        results.extend(self._check_stale_workspaces(session, region))
        results.extend(self._check_orphan_directories(session, region))
        results.extend(self._check_idle_storage_gateways(session, region))

        return results

    def _check_abandoned_vpcs(self, session: Any, region: str) -> list[CheckResult]:
        """Find VPCs with no running instances but still paying for NAT GWs, EIPs, endpoints.

        An "abandoned" VPC is one where:
        - Zero running EC2 instances in the VPC
        - But still has NAT Gateways, Elastic IPs, or Interface VPC Endpoints

        These are the most expensive waste patterns because multiple resources
        compound: NAT GW ($43/mo) + EIPs ($3.65/mo each) + endpoints ($7.30/mo/AZ).
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        #
        # # Step 1: Get all VPCs (exclude default VPC)
        # vpcs_resp = ec2_client.describe_vpcs()
        # vpcs = [
        #     v for v in vpcs_resp["Vpcs"]
        #     if not v.get("IsDefault", False)
        # ]
        #
        # for vpc in vpcs:
        #     vpc_id = vpc["VpcId"]
        #     tags = vpc.get("Tags", [])
        #     vpc_name = self.get_resource_name(tags)
        #
        #     # Step 2: Count running instances in this VPC
        #     instances_resp = ec2_client.describe_instances(
        #         Filters=[
        #             {"Name": "vpc-id", "Values": [vpc_id]},
        #             {"Name": "instance-state-name", "Values": ["running"]},
        #         ]
        #     )
        #     running_count = sum(
        #         len(r["Instances"])
        #         for r in instances_resp.get("Reservations", [])
        #     )
        #
        #     if running_count > 0:
        #         continue  # VPC has running workloads — skip
        #
        #     # Step 3: Check for stopped instances (VPC has only dead workloads)
        #     stopped_resp = ec2_client.describe_instances(
        #         Filters=[
        #             {"Name": "vpc-id", "Values": [vpc_id]},
        #             {"Name": "instance-state-name", "Values": ["stopped"]},
        #         ]
        #     )
        #     stopped_count = sum(
        #         len(r["Instances"])
        #         for r in stopped_resp.get("Reservations", [])
        #     )
        #
        #     # Step 4: Tally wasteful resources in this VPC
        #     vpc_waste_cost = 0.0
        #     waste_items: list[str] = []
        #
        #     # 4a: NAT Gateways
        #     nat_resp = ec2_client.describe_nat_gateways(
        #         Filters=[
        #             {"Name": "vpc-id", "Values": [vpc_id]},
        #             {"Name": "state", "Values": ["available"]},
        #         ]
        #     )
        #     nat_count = len(nat_resp.get("NatGateways", []))
        #     if nat_count > 0:
        #         nat_cost = nat_count * NAT_GATEWAY_MONTHLY_COST
        #         vpc_waste_cost += nat_cost
        #         waste_items.append(f"{nat_count} NAT GW(s) (${nat_cost:.0f}/mo)")
        #
        #     # 4b: Elastic IPs in this VPC (unassociated or associated with stopped instances)
        #     eips_resp = ec2_client.describe_addresses(
        #         Filters=[{"Name": "domain", "Values": ["vpc"]}]
        #     )
        #     vpc_eip_count = 0
        #     for eip in eips_resp.get("Addresses", []):
        #         # Check if EIP's ENI is in this VPC
        #         eni_id = eip.get("NetworkInterfaceId")
        #         if eni_id:
        #             eni_resp = ec2_client.describe_network_interfaces(
        #                 NetworkInterfaceIds=[eni_id]
        #             )
        #             enis = eni_resp.get("NetworkInterfaces", [])
        #             if enis and enis[0].get("VpcId") == vpc_id:
        #                 vpc_eip_count += 1
        #         elif not eip.get("AssociationId"):
        #             # Unassociated EIPs — can't determine VPC but still waste
        #             vpc_eip_count += 1
        #
        #     if vpc_eip_count > 0:
        #         eip_cost = vpc_eip_count * EIP_MONTHLY_COST
        #         vpc_waste_cost += eip_cost
        #         waste_items.append(f"{vpc_eip_count} EIP(s) (${eip_cost:.2f}/mo)")
        #
        #     # 4c: Interface VPC Endpoints (Gateway endpoints are free)
        #     endpoints_resp = ec2_client.describe_vpc_endpoints(
        #         Filters=[
        #             {"Name": "vpc-id", "Values": [vpc_id]},
        #             {"Name": "vpc-endpoint-type", "Values": ["Interface"]},
        #             {"Name": "vpc-endpoint-state", "Values": ["available"]},
        #         ]
        #     )
        #     endpoints = endpoints_resp.get("VpcEndpoints", [])
        #     if endpoints:
        #         # Each interface endpoint costs per AZ it's deployed in
        #         endpoint_cost = 0.0
        #         for ep in endpoints:
        #             az_count = len(ep.get("SubnetIds", []))
        #             az_count = max(az_count, 1)  # At least 1 AZ
        #             endpoint_cost += az_count * VPC_ENDPOINT_PER_AZ_MONTHLY
        #         vpc_waste_cost += endpoint_cost
        #         waste_items.append(
        #             f"{len(endpoints)} VPC endpoint(s) (${endpoint_cost:.0f}/mo)"
        #         )
        #
        #     # Step 5: Only flag if there's actual cost waste
        #     if vpc_waste_cost > 0:
        #         stopped_note = (
        #             f" ({stopped_count} stopped instance(s))"
        #             if stopped_count > 0
        #             else ""
        #         )
        #
        #         severity = "critical" if vpc_waste_cost > 200 else "high"
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="VPC (abandoned)",
        #             resource_id=vpc_id,
        #             resource_name=vpc_name,
        #             current_monthly_cost=vpc_waste_cost,
        #             recommended_action=(
        #                 f"Delete abandoned VPC{stopped_note} — "
        #                 f"still paying for: {', '.join(waste_items)}"
        #             ),
        #             estimated_monthly_savings=vpc_waste_cost,
        #             severity=severity,
        #             details={
        #                 "running_instances": 0,
        #                 "stopped_instances": stopped_count,
        #                 "nat_gateway_count": nat_count,
        #                 "eip_count": vpc_eip_count,
        #                 "endpoint_count": len(endpoints),
        #                 "waste_breakdown": waste_items,
        #                 "sub_check": "abandoned_vpc",
        #             },
        #         ))

        return results

    def _check_idle_nat_gateways(self, session: Any, region: str) -> list[CheckResult]:
        """Find NAT Gateways with zero data processed over 14 days.

        Unlike the main nat_gateway check (which focuses on non-prod NAT GWs),
        this sub-check specifically looks for NAT Gateways with absolutely zero
        traffic over a 14-day window — regardless of environment. A NAT Gateway
        processing zero bytes is definitively unused and safe to delete.
        """
        results: list[CheckResult] = []
        idle_days = self.config.thresholds.get("nat_idle_days", 14)

        # TODO: Uncomment and implement with real boto3 calls
        # ec2_client = session.client("ec2", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # paginator = ec2_client.get_paginator("describe_nat_gateways")
        # for page in paginator.paginate(
        #     Filters=[{"Name": "state", "Values": ["available"]}]
        # ):
        #     for ng in page["NatGateways"]:
        #         nat_id = ng["NatGatewayId"]
        #         vpc_id = ng["VpcId"]
        #         tags = ng.get("Tags", [])
        #         name = self.get_resource_name(tags)
        #
        #         # Query CloudWatch for bytes in AND out over idle_days
        #         end_time = datetime.now(timezone.utc)
        #         start_time = end_time - timedelta(days=idle_days)
        #
        #         bytes_out = cw_client.get_metric_statistics(
        #             Namespace="AWS/NATGateway",
        #             MetricName="BytesOutToDestination",
        #             Dimensions=[
        #                 {"Name": "NatGatewayId", "Value": nat_id},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400 * idle_days,
        #             Statistics=["Sum"],
        #         )
        #
        #         bytes_in = cw_client.get_metric_statistics(
        #             Namespace="AWS/NATGateway",
        #             MetricName="BytesInFromSource",
        #             Dimensions=[
        #                 {"Name": "NatGatewayId", "Value": nat_id},
        #             ],
        #             StartTime=start_time,
        #             EndTime=end_time,
        #             Period=86400 * idle_days,
        #             Statistics=["Sum"],
        #         )
        #
        #         total_out = sum(
        #             dp["Sum"] for dp in bytes_out.get("Datapoints", [])
        #         )
        #         total_in = sum(
        #             dp["Sum"] for dp in bytes_in.get("Datapoints", [])
        #         )
        #
        #         if total_out == 0 and total_in == 0:
        #             results.append(CheckResult(
        #                 check_name=self.name,
        #                 resource_type="NAT Gateway (idle)",
        #                 resource_id=nat_id,
        #                 resource_name=name or f"VPC: {vpc_id}",
        #                 current_monthly_cost=NAT_GATEWAY_FIXED_MONTHLY,
        #                 recommended_action=(
        #                     f"Delete — 0 bytes in/out over {idle_days} days"
        #                 ),
        #                 estimated_monthly_savings=NAT_GATEWAY_FIXED_MONTHLY,
        #                 severity="high",
        #                 details={
        #                     "vpc_id": vpc_id,
        #                     "bytes_out_14d": 0,
        #                     "bytes_in_14d": 0,
        #                     "idle_days_checked": idle_days,
        #                     "sub_check": "idle_nat_gateway",
        #                 },
        #             ))

        return results

    def _check_stale_workspaces(self, session: Any, region: str) -> list[CheckResult]:
        """Find WorkSpaces in STOPPED or UNHEALTHY state for 30+ days.

        WorkSpaces in STOPPED state still incur charges for the root and user
        volumes. UNHEALTHY WorkSpaces indicate connection or agent issues and
        are effectively unusable but still billed.
        """
        results: list[CheckResult] = []
        stale_days = self.config.thresholds.get("workspace_stale_days", 30)

        # TODO: Uncomment and implement with real boto3 calls
        # ws_client = session.client("workspaces", region_name=region)
        #
        # paginator = ws_client.get_paginator("describe_workspaces")
        # for page in paginator.paginate():
        #     for ws in page["Workspaces"]:
        #         ws_id = ws["WorkspaceId"]
        #         ws_state = ws["State"]
        #         bundle_id = ws.get("BundleId", "")
        #         username = ws.get("UserName", "(unknown)")
        #         directory_id = ws.get("DirectoryId", "")
        #
        #         # Only flag STOPPED or UNHEALTHY workspaces
        #         if ws_state not in ("STOPPED", "UNHEALTHY"):
        #             continue
        #
        #         # Check last known connection time via WorkSpaces API
        #         # describe_workspaces_connection_status gives last known time
        #         conn_resp = ws_client.describe_workspaces_connection_status(
        #             WorkspaceIds=[ws_id]
        #         )
        #         conn_statuses = conn_resp.get("WorkspacesConnectionStatus", [])
        #
        #         last_connected = None
        #         if conn_statuses:
        #             ts = conn_statuses[0].get("LastKnownUserConnectionTimestamp")
        #             if ts:
        #                 last_connected = ts
        #
        #         # Determine if stale (not connected for stale_days)
        #         days_since_connection = None
        #         if last_connected:
        #             days_since_connection = (
        #                 datetime.now(timezone.utc) - last_connected
        #             ).days
        #             if days_since_connection < stale_days:
        #                 continue  # Recently used — skip
        #
        #         # Estimate monthly cost from bundle type
        #         # Parse bundle name for cost lookup
        #         monthly_cost = WORKSPACES_DEFAULT_COST
        #         for bundle_key, cost in WORKSPACES_BUNDLE_COSTS.items():
        #             if bundle_key.lower() in bundle_id.lower():
        #                 monthly_cost = cost
        #                 break
        #
        #         days_label = (
        #             f"{days_since_connection} days since last connection"
        #             if days_since_connection is not None
        #             else "no connection data available"
        #         )
        #
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="WorkSpace",
        #             resource_id=ws_id,
        #             resource_name=f"{username} ({ws_state})",
        #             current_monthly_cost=monthly_cost,
        #             recommended_action=(
        #                 f"Terminate — {ws_state} workspace, {days_label}"
        #             ),
        #             estimated_monthly_savings=monthly_cost,
        #             severity="medium" if monthly_cost < 60 else "high",
        #             details={
        #                 "state": ws_state,
        #                 "username": username,
        #                 "directory_id": directory_id,
        #                 "bundle_id": bundle_id,
        #                 "days_since_connection": days_since_connection,
        #                 "sub_check": "stale_workspace",
        #             },
        #         ))

        return results

    def _check_orphan_directories(self, session: Any, region: str) -> list[CheckResult]:
        """Find Directory Services with no active WorkSpaces.

        A common pattern: WorkSpaces are deleted but the backing directory
        (SimpleAD, Microsoft AD, or AD Connector) is left running. These cost
        $72-360/month depending on type and size.
        """
        results: list[CheckResult] = []

        # TODO: Uncomment and implement with real boto3 calls
        # ws_client = session.client("workspaces", region_name=region)
        # ds_client = session.client("ds", region_name=region)
        #
        # # Step 1: Get all WorkSpaces directories registered with WorkSpaces
        # dir_resp = ws_client.describe_workspace_directories()
        # registered_dirs = {
        #     d["DirectoryId"]: d
        #     for d in dir_resp.get("Directories", [])
        # }
        #
        # # Step 2: For each registered directory, count active WorkSpaces
        # for dir_id, dir_info in registered_dirs.items():
        #     ws_resp = ws_client.describe_workspaces(
        #         DirectoryId=dir_id
        #     )
        #     workspaces = ws_resp.get("Workspaces", [])
        #
        #     # Count only AVAILABLE (active) WorkSpaces
        #     active_count = sum(
        #         1 for ws in workspaces
        #         if ws.get("State") == "AVAILABLE"
        #     )
        #
        #     if active_count > 0:
        #         continue  # Directory has active workspaces — skip
        #
        #     # Step 3: Look up directory details for type and cost
        #     dir_name = dir_info.get("DirectoryName", dir_id)
        #     dir_type = dir_info.get("DirectoryType", "Unknown")
        #
        #     monthly_cost = DIRECTORY_COSTS.get(dir_type, DIRECTORY_SIMPLE_AD_MONTHLY)
        #
        #     total_ws = len(workspaces)
        #     stopped_count = sum(
        #         1 for ws in workspaces
        #         if ws.get("State") in ("STOPPED", "UNHEALTHY")
        #     )
        #
        #     note = ""
        #     if total_ws > 0:
        #         note = f" ({stopped_count} stopped/unhealthy WorkSpace(s))"
        #     else:
        #         note = " (0 WorkSpaces)"
        #
        #     results.append(CheckResult(
        #         check_name=self.name,
        #         resource_type="Directory Service",
        #         resource_id=dir_id,
        #         resource_name=dir_name,
        #         current_monthly_cost=monthly_cost,
        #         recommended_action=(
        #             f"Delete — {dir_type} with no active WorkSpaces{note}"
        #         ),
        #         estimated_monthly_savings=monthly_cost,
        #         severity="high" if monthly_cost > 200 else "medium",
        #         details={
        #             "directory_type": dir_type,
        #             "total_workspaces": total_ws,
        #             "active_workspaces": 0,
        #             "stopped_workspaces": stopped_count,
        #             "sub_check": "orphan_directory",
        #         },
        #     ))

        return results

    def _check_idle_storage_gateways(self, session: Any, region: str) -> list[CheckResult]:
        """Find Storage Gateways with no recent activity.

        Storage Gateways running on EC2 incur instance costs plus storage.
        If no data has been transferred recently, the gateway may be abandoned.
        """
        results: list[CheckResult] = []
        idle_days = self.config.thresholds.get("storage_gw_idle_days", 30)

        # TODO: Uncomment and implement with real boto3 calls
        # sgw_client = session.client("storagegateway", region_name=region)
        # cw_client = session.client("cloudwatch", region_name=region)
        #
        # gateways_resp = sgw_client.list_gateways()
        # for gw in gateways_resp.get("Gateways", []):
        #     gw_arn = gw["GatewayARN"]
        #     gw_name = gw.get("GatewayName", gw_arn.split("/")[-1])
        #     gw_type = gw.get("GatewayType", "Unknown")
        #
        #     # Check CloudWatch for read/write bytes
        #     end_time = datetime.now(timezone.utc)
        #     start_time = end_time - timedelta(days=idle_days)
        #
        #     # Check ReadBytes metric
        #     read_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/StorageGateway",
        #         MetricName="ReadBytes",
        #         Dimensions=[
        #             {"Name": "GatewayId", "Value": gw_arn.split("/")[-1]},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400 * idle_days,
        #         Statistics=["Sum"],
        #     )
        #
        #     write_stats = cw_client.get_metric_statistics(
        #         Namespace="AWS/StorageGateway",
        #         MetricName="WriteBytes",
        #         Dimensions=[
        #             {"Name": "GatewayId", "Value": gw_arn.split("/")[-1]},
        #         ],
        #         StartTime=start_time,
        #         EndTime=end_time,
        #         Period=86400 * idle_days,
        #         Statistics=["Sum"],
        #     )
        #
        #     total_read = sum(
        #         dp["Sum"] for dp in read_stats.get("Datapoints", [])
        #     )
        #     total_write = sum(
        #         dp["Sum"] for dp in write_stats.get("Datapoints", [])
        #     )
        #
        #     if total_read == 0 and total_write == 0:
        #         results.append(CheckResult(
        #             check_name=self.name,
        #             resource_type="Storage Gateway",
        #             resource_id=gw_arn,
        #             resource_name=gw_name,
        #             current_monthly_cost=STORAGE_GATEWAY_MONTHLY_BASE,
        #             recommended_action=(
        #                 f"Delete — {gw_type} gateway with 0 bytes read/written "
        #                 f"over {idle_days} days"
        #             ),
        #             estimated_monthly_savings=STORAGE_GATEWAY_MONTHLY_BASE,
        #             severity="medium",
        #             details={
        #                 "gateway_type": gw_type,
        #                 "bytes_read": 0,
        #                 "bytes_written": 0,
        #                 "idle_days_checked": idle_days,
        #                 "sub_check": "idle_storage_gateway",
        #             },
        #         ))

        return results
