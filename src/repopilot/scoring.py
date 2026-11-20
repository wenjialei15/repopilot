from repopilot.models import Finding, Score


def calculate_score(findings: list[Finding], weights: dict[str, int]) -> Score:
    applicable_weight = 0
    evaluated_weight = 0
    passed_weight = 0
    for finding in findings:
        weight = weights[finding.rule_id]
        if finding.status == "skip":
            continue
        applicable_weight += weight
        if finding.status in {"pass", "fail"}:
            evaluated_weight += weight
        if finding.status == "pass":
            passed_weight += weight

    return Score(
        score=round(100 * passed_weight / evaluated_weight, 2)
        if evaluated_weight
        else None,
        coverage=round(100 * evaluated_weight / applicable_weight, 2)
        if applicable_weight
        else None,
        evaluated_weight=evaluated_weight,
        applicable_weight=applicable_weight,
    )
