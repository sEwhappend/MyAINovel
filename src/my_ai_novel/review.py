from __future__ import annotations

from typing import Any


VALID_ISSUE_TYPES = {
    "ooc",
    "world_conflict",
    "timeline_error",
    "foreshadowing",
    "goal_missing",
    "chatty_noise",
    "repetition",
    "pacing",
    "early_reveal",
}
VALID_SEVERITIES = {"low", "medium", "high"}


def validate_review_issues(data: dict[str, Any]) -> list[dict[str, str]]:
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("review issues must be a list")
    result = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("review issue must be an object")
        issue_type = str(issue.get("type", "pacing"))
        severity = str(issue.get("severity", "medium"))
        if issue_type not in VALID_ISSUE_TYPES:
            issue_type = "pacing"
        if severity not in VALID_SEVERITIES:
            severity = "medium"
        result.append(
            {
                "type": issue_type,
                "severity": severity,
                "location": str(issue.get("location", "")),
                "description": str(issue.get("description", "")),
                "suggestion": str(issue.get("suggestion", "")),
            }
        )
    return result


def build_rewrite_request(
    section: dict[str, Any],
    draft: str,
    issues: list[dict[str, Any]],
    mode: str,
    preserve: list[str],
) -> dict[str, Any]:
    return {
        "section": section,
        "draft": draft,
        "issues": issues,
        "rewrite_mode": mode,
        "preserve": preserve,
        "rules": [
            "只处理审稿意见相关问题",
            "保留用户指定句子或段落",
            "不要改变已确认设定",
            "输出 JSON object",
        ],
    }
