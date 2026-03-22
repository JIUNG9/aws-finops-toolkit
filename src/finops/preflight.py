"""Pre-flight analysis module — gather context before any cost optimization.

Runs 9 analysis checks against a target resource before recommending
any cost changes. Integrates with AWS CloudWatch and optional APM
providers (SigNoz, Datadog, Prometheus) to build a complete picture.

All thresholds and rules are driven by finops.yaml configuration,
making this tool generic for any AWS environment.

This is the SRE gate: never optimize what you don't fully understand.

Usage:
    finops preflight --target <instance-id|service-name> --profile <aws-profile>
    finops preflight --target my-rds-prod --profile production --apm signoz
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from finops.config import FinOpsConfig, PreflightConfig, ServiceConfig


class Verdict(Enum):
    """Pre-flight recommendation verdict."""
    GO = "go"           # Safe to proceed with optimization
    WAIT = "wait"       # Conditions not ideal — wait for a better window
    STOP = "stop"       # Do not optimize — reliability risk too high


class Severity(Enum):
    """Finding severity for pre-flight checks."""
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass
class TrafficAnalysis:
    """Check 1: TPS/QPS and peak traffic patterns."""
    current_qps: float = 0.0
    peak_qps_30d: float = 0.0
    peak_to_avg_ratio: float = 0.0
    peak_hours: list[str] = field(default_factory=list)     # e.g., ["11:00-13:00", "18:00-20:00"]
    weekend_drop_pct: float = 0.0                           # e.g., -57.0
    pattern_type: str = "unknown"                           # "stable", "spiky", "seasonal"


@dataclass
class QualityOfService:
    """Check 2: Current SLO status and error budget."""
    p99_latency_ms: float = 0.0
    p99_target_ms: float = 200.0
    availability_pct: float = 0.0
    availability_target_pct: float = 99.9
    error_rate_pct: float = 0.0
    error_budget_remaining_pct: float = 0.0
    # Thresholds from config (set by analyzer, not hardcoded)
    budget_go_threshold: float = 70.0
    budget_warn_threshold: float = 40.0

    @property
    def latency_headroom_pct(self) -> float:
        if self.p99_target_ms == 0:
            return 0.0
        return (1 - self.p99_latency_ms / self.p99_target_ms) * 100

    @property
    def budget_status(self) -> str:
        """GREEN / YELLOW / RED based on configured thresholds."""
        if self.error_budget_remaining_pct > self.budget_go_threshold:
            return "GREEN"
        elif self.error_budget_remaining_pct > self.budget_warn_threshold:
            return "YELLOW"
        return "RED"


@dataclass
class CacheAnalysis:
    """Check 3: Cache strategy and dependency."""
    cache_cluster_id: str = ""
    hit_rate_pct: float = 0.0
    eviction_rate: float = 0.0
    ttl_seconds: int = 0
    cache_miss_qps: float = 0.0          # QPS that reaches backend on cache miss
    strategy: str = ""                    # "read-through", "write-behind", "aside"

    @property
    def backend_load_without_cache_pct(self) -> float:
        """Estimated backend load multiplier if cache fails completely.

        If cache handles 87% of requests, only 13% reach backend.
        Without cache, backend load would be ~7.7x current (100/13).
        Returns the multiplier as a percentage (770% in this example).
        """
        if self.hit_rate_pct <= 0:
            return 100.0  # No cache — backend already handles 100%
        if self.hit_rate_pct >= 100:
            return float("inf")  # 100% cache — backend would go from 0 to all traffic
        miss_rate = (100.0 - self.hit_rate_pct) / 100.0
        return 100.0 / miss_rate


@dataclass
class Incident:
    """A single incident record."""
    date: str
    title: str
    severity: str                   # "P0", "P1", "P2", "P3"
    capacity_related: bool = False
    resolved: bool = True
    resolution_minutes: int = 0


@dataclass
class IncidentHistory:
    """Check 4: Recent incident history."""
    incidents: list[Incident] = field(default_factory=list)
    lookback_days: int = 90
    capacity_cooldown_days: int = 60    # From config: preflight.incidents.capacity_cooldown_days

    @property
    def total_count(self) -> int:
        return len(self.incidents)

    @property
    def capacity_related_count(self) -> int:
        return sum(1 for i in self.incidents if i.capacity_related)

    @property
    def has_recent_capacity_incident(self) -> bool:
        """Any capacity-related incident within the cooldown window."""
        # TODO: filter by date within capacity_cooldown_days (not just presence)
        return self.capacity_related_count > 0


@dataclass
class AccessStatus:
    """Check 5: Credential and permission validation."""
    aws_profile: str = ""
    aws_account_id: str = ""
    aws_region: str = ""
    permissions_valid: bool = False
    apm_connected: bool = False
    apm_provider: str = ""          # "signoz", "datadog", "prometheus"


@dataclass
class TargetMapping:
    """Check 6: Resource → service → APM mapping."""
    resource_id: str = ""           # e.g., "i-0abc123", "pn-sh-rds-prod"
    resource_type: str = ""         # e.g., "EC2", "RDS", "ElastiCache"
    instance_type: str = ""         # e.g., "db.r6g.xlarge"
    service_name: str = ""          # e.g., "gateway-server"
    apm_dashboard: str = ""         # e.g., SigNoz dashboard URL
    dependent_services: list[str] = field(default_factory=list)
    owner_team: str = ""

    @property
    def blast_radius(self) -> str:
        """HIGH if 3+ dependents, MEDIUM if 1-2, LOW if 0."""
        count = len(self.dependent_services)
        if count >= 3:
            return "HIGH"
        elif count >= 1:
            return "MEDIUM"
        return "LOW"


@dataclass
class ResourceMetrics:
    """Detailed resource utilization metrics (14-day window)."""
    cpu_avg_pct: float = 0.0
    cpu_peak_pct: float = 0.0
    memory_avg_pct: float = 0.0
    connections_avg: int = 0
    connections_max: int = 0
    iops_avg: int = 0
    iops_provisioned: int = 0


@dataclass
class TrafficPattern:
    """Check 7: Traffic pattern and service specification."""
    weekday_avg_qps: float = 0.0
    weekend_avg_qps: float = 0.0
    is_stateless: bool = False          # Can use Spot?
    is_schedulable: bool = False        # Can scale down off-hours?
    dependencies_upstream: list[str] = field(default_factory=list)
    dependencies_downstream: list[str] = field(default_factory=list)
    seasonal_notes: str = ""            # e.g., "month-end spike", "holiday peak"
    holiday_calendar: list[str] = field(default_factory=list)  # e.g., ["Chuseok 2026-09-14..09-17", "Lunar New Year 2027-01-28..01-30"]
    batch_schedules: list[str] = field(default_factory=list)   # e.g., ["daily 02:00 UTC ETL", "monthly 1st billing-run"]
    has_holiday_pattern: bool = False     # True if traffic spikes correlate with holidays
    has_batch_system: bool = False        # True if batch jobs affect resource utilization


@dataclass
class PriorityCheck:
    """Check 8: Organizational readiness — freeze, priority, severity."""
    service_priority: str = ""          # "P0", "P1", "P2", "P3"
    deploy_freeze_active: bool = False
    pending_release: str = ""           # e.g., "ConnectOrder v2.3 — March 18"
    pending_release_date: str = ""
    active_incidents: int = 0
    error_trend: str = "stable"         # "improving", "stable", "degrading"
    team_available: bool = True
    requires_approval: bool = False     # P0/P1 services need approval
    approval_from: str = ""             # e.g., "team lead + SRE"


@dataclass
class RISPCoverage:
    """Check 9: Existing Reserved Instance / Savings Plan coverage."""
    active_ris: list[dict[str, Any]] = field(default_factory=list)  # [{instance_type, count, end_date, scope}]
    active_savings_plans: list[dict[str, Any]] = field(default_factory=list)  # [{type, commitment, end_date}]
    target_covered_by_ri: bool = False
    target_covered_by_sp: bool = False
    ri_waste_risk: bool = False  # True if downsizing would waste an RI
    sp_family_break_risk: bool = False  # True if instance family change breaks EC2 Instance SP

    @property
    def has_coverage_conflict(self) -> bool:
        """True if downsizing this target would conflict with existing commitments."""
        return self.ri_waste_risk or self.sp_family_break_risk


@dataclass
class PreflightFinding:
    """A single finding from the pre-flight analysis."""
    check_name: str                     # Which of the 8 checks
    message: str
    severity: Severity = Severity.INFO
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightResult:
    """Complete pre-flight analysis result."""
    target: str
    account: str
    region: str
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # The 9 analysis sections
    traffic: TrafficAnalysis = field(default_factory=TrafficAnalysis)
    qos: QualityOfService = field(default_factory=QualityOfService)
    cache: CacheAnalysis = field(default_factory=CacheAnalysis)
    incidents: IncidentHistory = field(default_factory=IncidentHistory)
    access: AccessStatus = field(default_factory=AccessStatus)
    target_mapping: TargetMapping = field(default_factory=TargetMapping)
    resource_metrics: ResourceMetrics = field(default_factory=ResourceMetrics)
    traffic_pattern: TrafficPattern = field(default_factory=TrafficPattern)
    priority: PriorityCheck = field(default_factory=PriorityCheck)
    ri_sp: RISPCoverage = field(default_factory=RISPCoverage)

    # Aggregated findings
    findings: list[PreflightFinding] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        """Determine go/wait/stop based on all findings."""
        blockers = [f for f in self.findings if f.severity == Severity.BLOCKER]
        warnings = [f for f in self.findings if f.severity == Severity.WARNING]

        if blockers:
            return Verdict.STOP
        if warnings:
            return Verdict.WAIT
        return Verdict.GO

    @property
    def recommendation(self) -> str:
        """Human-readable recommendation string."""
        v = self.verdict
        if v == Verdict.GO:
            return "SAFE TO PROCEED — schedule optimization at off-peak window"
        elif v == Verdict.WAIT:
            reasons = [f.message for f in self.findings if f.severity == Severity.WARNING]
            return f"WAIT — resolve before proceeding: {'; '.join(reasons)}"
        else:
            reasons = [f.message for f in self.findings if f.severity == Severity.BLOCKER]
            return f"STOP — blocking issues: {'; '.join(reasons)}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON export."""
        return {
            "target": self.target,
            "account": self.account,
            "region": self.region,
            "analyzed_at": self.analyzed_at.isoformat(),
            "verdict": self.verdict.value,
            "recommendation": self.recommendation,
            "findings_count": {
                "blocker": sum(1 for f in self.findings if f.severity == Severity.BLOCKER),
                "warning": sum(1 for f in self.findings if f.severity == Severity.WARNING),
                "info": sum(1 for f in self.findings if f.severity == Severity.INFO),
            },
            "traffic": {
                "current_qps": self.traffic.current_qps,
                "peak_qps_30d": self.traffic.peak_qps_30d,
                "peak_to_avg_ratio": self.traffic.peak_to_avg_ratio,
                "peak_hours": self.traffic.peak_hours,
            },
            "qos": {
                "p99_latency_ms": self.qos.p99_latency_ms,
                "p99_target_ms": self.qos.p99_target_ms,
                "availability_pct": self.qos.availability_pct,
                "error_budget_remaining_pct": self.qos.error_budget_remaining_pct,
                "budget_status": self.qos.budget_status,
            },
            "cache": {
                "hit_rate_pct": self.cache.hit_rate_pct,
                "eviction_rate": self.cache.eviction_rate,
                "backend_load_without_cache_pct": self.cache.backend_load_without_cache_pct,
            },
            "incidents": {
                "total_90d": self.incidents.total_count,
                "capacity_related": self.incidents.capacity_related_count,
            },
            "resource_metrics": {
                "cpu_avg_pct": self.resource_metrics.cpu_avg_pct,
                "cpu_peak_pct": self.resource_metrics.cpu_peak_pct,
                "memory_avg_pct": self.resource_metrics.memory_avg_pct,
            },
            "target_mapping": {
                "resource_id": self.target_mapping.resource_id,
                "instance_type": self.target_mapping.instance_type,
                "service_name": self.target_mapping.service_name,
                "blast_radius": self.target_mapping.blast_radius,
                "dependent_services": self.target_mapping.dependent_services,
            },
            "traffic_pattern": {
                "weekday_avg_qps": self.traffic_pattern.weekday_avg_qps,
                "weekend_avg_qps": self.traffic_pattern.weekend_avg_qps,
                "is_stateless": self.traffic_pattern.is_stateless,
                "is_schedulable": self.traffic_pattern.is_schedulable,
            },
            "priority": {
                "service_priority": self.priority.service_priority,
                "deploy_freeze": self.priority.deploy_freeze_active,
                "pending_release": self.priority.pending_release,
                "requires_approval": self.priority.requires_approval,
                "approval_from": self.priority.approval_from,
            },
            "ri_sp": {
                "target_covered_by_ri": self.ri_sp.target_covered_by_ri,
                "target_covered_by_sp": self.ri_sp.target_covered_by_sp,
                "ri_waste_risk": self.ri_sp.ri_waste_risk,
                "sp_family_break_risk": self.ri_sp.sp_family_break_risk,
                "active_ris_count": len(self.ri_sp.active_ris),
                "active_sps_count": len(self.ri_sp.active_savings_plans),
            },
            "findings": [
                {
                    "check": f.check_name,
                    "severity": f.severity.value,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.findings
            ],
        }


class PreflightAnalyzer:
    """Runs the 9-check pre-flight analysis against a target resource.

    Integrates with:
    - AWS CloudWatch for traffic and resource metrics
    - AWS EC2/RDS/ElastiCache APIs for resource details
    - APM provider (SigNoz) for SLO/error budget data
    - Incident history sources
    """

    def __init__(self, config: FinOpsConfig) -> None:
        self.config = config
        self.pf: PreflightConfig = config.preflight

    def analyze(
        self,
        target: str,
        session,  # boto3.Session
        region: str = "us-east-1",
        apm_provider: Optional[str] = None,
        apm_endpoint: Optional[str] = None,
    ) -> PreflightResult:
        """Run all 9 pre-flight checks and return aggregated result.

        All thresholds and rules are driven by finops.yaml configuration.
        CLI flags (apm_provider, apm_endpoint) override config values.

        Args:
            target: Resource identifier (instance ID, DB identifier, or service name)
            session: boto3 Session for AWS API calls
            region: AWS region
            apm_provider: APM provider override (falls back to config.preflight.apm.provider)
            apm_endpoint: APM endpoint override (falls back to config.preflight.apm.endpoint)
        """
        # Resolve APM settings: CLI flags > config > default (cloudwatch)
        effective_apm_provider = apm_provider or self.pf.apm.get("provider", "cloudwatch")
        effective_apm_endpoint = apm_endpoint or self.pf.apm.get("endpoint", "")
        effective_apm_key_env = self.pf.apm.get("api_key_env", "")

        # Resolve service catalog entry for this target (if configured)
        svc = self.pf.get_service(target) or self.pf.get_service_by_resource(target)

        # Resolve SLO targets: per-service override > global config
        slo_targets = self.pf.get_slo_for_service(target) if svc else dict(self.pf.slo)

        result = PreflightResult(
            target=target,
            account="",  # TODO: resolve from session via sts:GetCallerIdentity
            region=region,
        )

        # ── Check 1: Traffic analysis ────────────────────────────────
        traffic_config = self.pf.traffic
        result.traffic = self._analyze_traffic(
            target, session, region,
            lookback_days=traffic_config.get("lookback_days", 30),
        )
        peak_warn = traffic_config.get("peak_avg_ratio_warn", 3.0)
        if result.traffic.peak_to_avg_ratio > peak_warn:
            result.findings.append(PreflightFinding(
                check_name="traffic",
                message=f"High peak:avg ratio ({result.traffic.peak_to_avg_ratio:.1f}x, threshold: {peak_warn}x) — careful with right-sizing",
                severity=Severity.WARNING,
                details={"peak_qps": result.traffic.peak_qps_30d, "avg_qps": result.traffic.current_qps},
            ))

        # ── Check 2: Quality of Service ──────────────────────────────
        if effective_apm_provider != "cloudwatch" and effective_apm_endpoint:
            result.qos = self._analyze_qos(
                target, effective_apm_provider, effective_apm_endpoint,
                api_key_env=effective_apm_key_env,
                slo_targets=slo_targets,
            )
        else:
            result.qos = self._analyze_qos_cloudwatch(target, session, region, slo_targets=slo_targets)

        # Apply configured error budget thresholds
        go_threshold = slo_targets.get("error_budget_go_pct", 70)
        warn_threshold = slo_targets.get("error_budget_warn_pct", 40)
        budget = result.qos.error_budget_remaining_pct
        if budget < warn_threshold:
            result.findings.append(PreflightFinding(
                check_name="qos",
                message=f"Error budget critically low ({budget:.0f}%, threshold: {warn_threshold}%)",
                severity=Severity.BLOCKER,
            ))
        elif budget < go_threshold:
            result.findings.append(PreflightFinding(
                check_name="qos",
                message=f"Error budget at {budget:.0f}% (need >{go_threshold}% for full optimization) — limit to low-risk",
                severity=Severity.WARNING,
            ))

        # ── Check 3: Cache dependency ────────────────────────────────
        cache_cluster = svc.cache_cluster if svc else ""
        result.cache = self._analyze_cache(target, session, region, cache_cluster=cache_cluster)
        cache_warn = self.pf.cache.get("high_dependency_pct", 80)
        if result.cache.hit_rate_pct > cache_warn:
            result.findings.append(PreflightFinding(
                check_name="cache",
                message=f"High cache dependency ({result.cache.hit_rate_pct:.0f}% hit rate, threshold: {cache_warn}%) — backend CPU is misleading",
                severity=Severity.WARNING,
                details={"backend_load_without_cache": result.cache.backend_load_without_cache_pct},
            ))

        # ── Check 4: Incident history ────────────────────────────────
        inc_config = self.pf.incidents
        result.incidents = self._analyze_incidents(
            target, session, region,
            lookback_days=inc_config.get("lookback_days", 90),
            source=inc_config.get("source", "cloudwatch"),
        )
        cooldown = inc_config.get("capacity_cooldown_days", 60)
        if result.incidents.has_recent_capacity_incident:
            result.findings.append(PreflightFinding(
                check_name="incidents",
                message=f"Capacity-related incident within {cooldown}-day cooldown ({result.incidents.capacity_related_count} found)",
                severity=Severity.WARNING,
            ))

        # ── Check 5: Access validation ───────────────────────────────
        result.access = self._validate_access(
            session, region,
            effective_apm_provider, effective_apm_endpoint,
        )
        if not result.access.permissions_valid:
            result.findings.append(PreflightFinding(
                check_name="access",
                message="Insufficient AWS permissions for analysis",
                severity=Severity.BLOCKER,
            ))

        # ── Check 6: Target mapping ──────────────────────────────────
        result.target_mapping = self._map_target(target, session, region, service_config=svc)
        result.resource_metrics = self._get_resource_metrics(target, session, region)

        if result.target_mapping.blast_radius == "HIGH":
            result.findings.append(PreflightFinding(
                check_name="target_mapping",
                message=f"High blast radius — {len(result.target_mapping.dependent_services)} dependent services",
                severity=Severity.WARNING,
                details={"dependents": result.target_mapping.dependent_services},
            ))

        # ── Check 7: Traffic pattern ─────────────────────────────────
        result.traffic_pattern = self._analyze_traffic_pattern(
            target, session, region, service_config=svc,
        )
        if result.traffic_pattern.has_holiday_pattern:
            result.findings.append(PreflightFinding(
                check_name="traffic_pattern",
                message="Holiday traffic spikes detected — freeze FinOps changes 2 weeks before holiday periods",
                severity=Severity.WARNING,
                details={"holidays": result.traffic_pattern.holiday_calendar},
            ))
        if result.traffic_pattern.has_batch_system:
            result.findings.append(PreflightFinding(
                check_name="traffic_pattern",
                message="Batch system detected — size for batch peak, not daily average",
                severity=Severity.WARNING,
                details={"batch_schedules": result.traffic_pattern.batch_schedules},
            ))

        # ── Check 8: Priority and freeze check ──────────────────────
        result.priority = self._check_priority(
            target, session, region, service_config=svc,
        )
        if result.priority.deploy_freeze_active:
            result.findings.append(PreflightFinding(
                check_name="priority",
                message="Deployment freeze is active",
                severity=Severity.BLOCKER,
            ))
        if result.priority.active_incidents > 0:
            result.findings.append(PreflightFinding(
                check_name="priority",
                message=f"{result.priority.active_incidents} active incident(s) on target service",
                severity=Severity.BLOCKER,
            ))
        if result.priority.pending_release:
            result.findings.append(PreflightFinding(
                check_name="priority",
                message=f"Pending release: {result.priority.pending_release}",
                severity=Severity.WARNING,
            ))
        if result.priority.error_trend == "degrading":
            result.findings.append(PreflightFinding(
                check_name="priority",
                message="Error rate trending upward — do not add risk",
                severity=Severity.BLOCKER,
            ))

        # ── Check 9: RI/SP coverage ──────────────────────────────
        result.ri_sp = self._analyze_ri_sp(target, session, region)
        if result.ri_sp.ri_waste_risk:
            result.findings.append(PreflightFinding(
                check_name="ri_sp",
                message="Target is covered by a Reserved Instance — downsizing would waste the reservation",
                severity=Severity.WARNING,
                details={"active_ris": result.ri_sp.active_ris},
            ))
        if result.ri_sp.sp_family_break_risk:
            result.findings.append(PreflightFinding(
                check_name="ri_sp",
                message="Changing instance family would break EC2 Instance Savings Plan coverage",
                severity=Severity.WARNING,
            ))

        return result

    # ── Individual check implementations ─────────────────────────────
    #
    # Each method accepts config-driven parameters instead of hardcoded values.
    # If a service catalog entry exists, it's used for discovery shortcuts
    # (dependencies, cache cluster, stateless flag, etc.).
    # Otherwise, fall back to AWS tag-based discovery.

    def _analyze_traffic(
        self, target: str, session, region: str,
        lookback_days: int = 30,
    ) -> TrafficAnalysis:
        """Check 1: Pull TPS/QPS and peak patterns from CloudWatch.

        Uses config: preflight.traffic.lookback_days
        """
        # TODO: Implement CloudWatch queries
        # - Detect resource type from target (i-xxx → EC2, db-xxx → RDS, etc.)
        # - ALB RequestCount for web services (needs ALB ARN from tags or config)
        # - RDS DatabaseConnections for databases
        # - ElastiCache CurrConnections for caches
        # - Pull {lookback_days} of hourly data
        # - Calculate current avg, peak, ratio, peak hours
        return TrafficAnalysis()

    def _analyze_qos(
        self, target: str, provider: str, endpoint: str,
        api_key_env: str = "",
        slo_targets: Optional[dict[str, Any]] = None,
    ) -> QualityOfService:
        """Check 2: Query external APM provider for SLO status.

        Uses config: preflight.apm (provider, endpoint, api_key_env)
        Uses config: preflight.slo or per-service slo overrides

        Supported providers:
          - signoz: GET {endpoint}/api/v1/services/{service}/slo
          - datadog: GET {endpoint}/api/v1/slo (requires DD_API_KEY)
          - prometheus: PromQL query against {endpoint}/api/v1/query
        """
        slo = slo_targets or self.pf.slo
        # TODO: Implement per-provider API integration
        # - Resolve API key from env var: os.environ.get(api_key_env, "")
        # - Query p99 latency, availability, error rate
        # - Calculate error budget: (target - actual) / target * 30 days
        # - Apply slo targets from config
        result = QualityOfService()
        result.p99_target_ms = slo.get("p99_latency_ms", 200)
        result.availability_target_pct = slo.get("availability_pct", 99.9)
        return result

    def _analyze_qos_cloudwatch(
        self, target: str, session, region: str,
        slo_targets: Optional[dict[str, Any]] = None,
    ) -> QualityOfService:
        """Check 2 (fallback): Estimate QoS from CloudWatch metrics.

        Uses config: preflight.slo targets

        When no external APM is configured, estimate SLO status from:
          - ALB TargetResponseTime (p99)
          - ALB HTTPCode_Target_5XX_Count / RequestCount (error rate)
          - Availability = 1 - (5xx / total)
        """
        slo = slo_targets or self.pf.slo
        # TODO: Implement CloudWatch-based SLO estimation
        result = QualityOfService()
        result.p99_target_ms = slo.get("p99_latency_ms", 200)
        result.availability_target_pct = slo.get("availability_pct", 99.9)
        return result

    def _analyze_cache(
        self, target: str, session, region: str,
        cache_cluster: str = "",
    ) -> CacheAnalysis:
        """Check 3: Analyze cache dependency.

        Uses config: preflight.cache.high_dependency_pct
        Uses config: preflight.services[].cache_cluster (if defined)

        If cache_cluster is provided (from service catalog), use it directly.
        Otherwise, discover by checking:
          - ElastiCache tags matching the target service name
          - EC2 security group associations
        """
        # TODO: Implement cache analysis
        # - If cache_cluster provided: query it directly
        # - Else: discover via DescribeCacheClusters + tag matching
        # - Pull CacheHitRate, Evictions, CurrItems metrics
        # - Calculate backend_load_without_cache
        return CacheAnalysis()

    def _analyze_incidents(
        self, target: str, session, region: str,
        lookback_days: int = 90,
        source: str = "cloudwatch",
    ) -> IncidentHistory:
        """Check 4: Pull incident history.

        Uses config: preflight.incidents (lookback_days, capacity_cooldown_days, source)

        Supported sources:
          - cloudwatch: DescribeAlarmHistory for target-related alarms
          - pagerduty: PagerDuty API incidents for the service
          - opsgenie: Opsgenie API alerts for the service
        """
        # TODO: Implement per-source incident history
        # - CloudWatch: describe-alarm-history, filter by target name/ID
        # - PagerDuty: GET /incidents?service_ids[]= (requires PD_API_KEY)
        # - OpsGenie: GET /v2/alerts?query=tag:service:{target}
        # - Filter for capacity-related incidents (keyword matching)
        return IncidentHistory(lookback_days=lookback_days)

    def _validate_access(
        self, session, region: str,
        apm_provider: Optional[str], apm_endpoint: Optional[str],
    ) -> AccessStatus:
        """Check 5: Validate AWS credentials and APM connectivity.

        Verifies:
          - AWS credentials are valid (sts:GetCallerIdentity)
          - Required permissions exist (cloudwatch:GetMetricStatistics, ec2:Describe*, etc.)
          - APM endpoint is reachable (if configured)
        """
        # TODO: Implement credential validation
        # - sts:GetCallerIdentity → account ID, ARN
        # - Dry-run a CloudWatch GetMetricStatistics call
        # - If APM configured, test endpoint connectivity (HTTP GET /api/v1/health)
        return AccessStatus()

    def _map_target(
        self, target: str, session, region: str,
        service_config: Optional[ServiceConfig] = None,
    ) -> TargetMapping:
        """Check 6: Map resource → service → APM dashboard.

        Uses config: preflight.services[] (if defined)

        If a service catalog entry exists, use it for dependencies and owner.
        Otherwise, discover from AWS tags:
          - "Service" tag → service name
          - "Team" / "Owner" tag → owner
          - "Priority" tag → priority level
        """
        mapping = TargetMapping(resource_id=target)

        # Use service catalog if available
        if service_config:
            mapping.service_name = service_config.name
            mapping.dependent_services = (
                service_config.dependencies_upstream + service_config.dependencies_downstream
            )
            # TODO: resolve instance_type from AWS API
        else:
            pass
            # TODO: Discover from AWS tags
            # - ec2:DescribeInstances / rds:DescribeDBInstances
            # - Parse tags: Service, Team, Owner, Priority

        return mapping

    def _get_resource_metrics(self, target: str, session, region: str) -> ResourceMetrics:
        """Get detailed resource utilization metrics (14-day window).

        Uses config: preflight.traffic.lookback_days for metric window

        Metrics per resource type:
          - EC2: CPUUtilization, MemoryUtilization (requires CW agent)
          - RDS: CPUUtilization, FreeableMemory, DatabaseConnections, ReadIOPS, WriteIOPS
          - ElastiCache: CPUUtilization, CurrConnections, CacheHitRate
        """
        # TODO: Implement per-resource-type CloudWatch queries
        return ResourceMetrics()

    def _analyze_traffic_pattern(
        self, target: str, session, region: str,
        service_config: Optional[ServiceConfig] = None,
    ) -> TrafficPattern:
        """Check 7: Analyze weekly/monthly traffic patterns.

        Uses config: preflight.services[].stateless (if defined)
        Uses config: preflight.traffic.lookback_days

        If service catalog defines stateless=true, skip Spot eligibility check.
        Otherwise, determine from:
          - ASG/EKS node group settings (stateless heuristic)
          - Tag: "Stateless=true"
        """
        pattern = TrafficPattern()

        if service_config:
            pattern.is_stateless = service_config.stateless
            pattern.dependencies_upstream = service_config.dependencies_upstream
            pattern.dependencies_downstream = service_config.dependencies_downstream

        # TODO: Pull 30-day hourly metrics
        # - Calculate weekday vs weekend averages
        # - Identify peak windows and seasonal notes
        # - Determine schedulability (dev/staging heuristic from account name/tags)
        return pattern

    def _check_priority(
        self, target: str,
        session=None, region: str = "",
        service_config: Optional[ServiceConfig] = None,
    ) -> PriorityCheck:
        """Check 8: Check organizational readiness.

        Uses config: preflight.priority (tag_key, freeze_tag_key, levels)
        Uses config: preflight.services[].priority (if defined)

        Automatically checks:
          - Priority level from tags or service catalog
          - Deploy freeze from tag (preflight.priority.freeze_tag_key)
          - Active CloudWatch alarms in ALARM state for target
          - Error rate trend from last 7 days
        Requires manual input / external integration:
          - Pending releases (Jira, Linear, Sprint board)
          - Team availability
        """
        priority_config = self.pf.priority
        tag_key = priority_config.get("tag_key", "Priority")

        check = PriorityCheck()

        # Use service catalog priority if available
        if service_config:
            check.service_priority = service_config.priority
        # else: TODO: read from AWS tag {tag_key}

        # Apply rules from config
        if check.service_priority:
            rules = self.pf.get_priority_rules(check.service_priority)
            check.requires_approval = rules.get("requires_approval", False)
            check.approval_from = rules.get("approval_from", "")

        # TODO: Check deploy freeze tag on resource/account
        # TODO: Check active CloudWatch alarms for target
        # TODO: Calculate error rate trend (7-day linear regression)
        return check

    def _analyze_ri_sp(
        self, target: str, session, region: str,
    ) -> RISPCoverage:
        """Check 9: Analyze existing Reserved Instance and Savings Plan coverage.

        Before any downsize, verify:
          - Target instance is not covered by an active RI (downsizing wastes it)
          - Instance family change won't break EC2 Instance SP coverage
          - Compute Savings Plans are flexible (family change OK)

        AWS APIs:
          - ec2:DescribeReservedInstances
          - savingsplans:DescribeSavingsPlans
        """
        # TODO: Implement RI/SP coverage analysis
        # - List active RIs: ec2.describe_reserved_instances(Filters=[{State: active}])
        # - List active SPs: savingsplans.describe_savings_plans(States=[active])
        # - Match target instance type against RI instance types
        # - Check SP type: "Compute" (flexible) vs "EC2Instance" (family-locked)
        # - If target matches RI → ri_waste_risk = True
        # - If SP is EC2Instance and downsize changes family → sp_family_break_risk = True
        return RISPCoverage()
