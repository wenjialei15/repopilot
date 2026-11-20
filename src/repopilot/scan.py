from repopilot.adapters.base import RepositoryAdapter
from repopilot.config import ScanConfig
from repopilot.models import ScanReport
from repopilot.rules import DEFAULT_RULES, RuleContext
from repopilot.scoring import calculate_score


def scan_repository(
    repository: RepositoryAdapter, config: ScanConfig | None = None
) -> ScanReport:
    weights = {rule.rule_id: rule.weight for rule in DEFAULT_RULES.rules}
    if config and config.rules.keys() - weights.keys():
        raise ValueError("Configuration references an unknown rule ID.")
    disabled = config.disabled_rules if config else frozenset()
    findings = DEFAULT_RULES.evaluate(RuleContext(repository), disabled)
    return ScanReport(
        repository=repository.name,
        is_git_repository=repository.is_git_repository,
        findings=findings,
        summary=calculate_score(findings, weights),
    )
