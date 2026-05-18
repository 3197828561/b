"""标书合规终检（AI）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..utils.openai_util import OpenAIUtil
from ..utils.prompts.compliance_prompts import build_compliance_check_messages
from .coverage_service import check_scoring_coverage


class ComplianceIssue(BaseModel):
    severity: str = "中"
    category: str = ""
    message: str = ""
    suggestion: str = ""


class ComplianceCheckResult(BaseModel):
    passed: bool = True
    risk_level: str = "低"
    summary: str = ""
    issues: list[ComplianceIssue] = Field(default_factory=list)
    coverage_rate: float = 1.0
    uncovered_scoring_count: int = 0


def _summarize_outline(outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def walk(items: list[dict[str, Any]], parents: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in items:
            title = str(it.get("title") or "")
            path = " > ".join(parents + [title]) if title else ""
            children = it.get("children") or []
            if children:
                out.extend(walk(children, parents + [title]))
            else:
                content = str(it.get("content") or "").strip()
                out.append(
                    {
                        "id": it.get("id"),
                        "path": path,
                        "has_content": bool(content),
                        "content_preview": content[:200] if content else "",
                        "source_requirement_id": it.get("source_requirement_id"),
                    }
                )
        return out

    return walk(outline, [])


class ComplianceService:
    def __init__(self, ai: OpenAIUtil | None = None):
        self.ai = ai or OpenAIUtil()

    async def run_check(
        self,
        project_overview: str,
        tech_requirements: str,
        scoring_groups: list[dict[str, Any]],
        outline: list[dict[str, Any]],
    ) -> ComplianceCheckResult:
        coverage = check_scoring_coverage(scoring_groups, outline)
        outline_summary = _summarize_outline(outline)

        messages = build_compliance_check_messages(
            project_overview=project_overview,
            tech_requirements=tech_requirements,
            scoring_groups=scoring_groups,
            outline_summary=outline_summary,
        )

        raw = await self.ai.collect_json_response(
            messages=messages,
            temperature=0.2,
            schema=ComplianceCheckResult,
            failure_message="合规检查返回格式无效",
        )

        result = ComplianceCheckResult.model_validate(raw)
        result.coverage_rate = float(coverage.get("coverage_rate") or 0)
        result.uncovered_scoring_count = int(coverage.get("uncovered_count") or 0)

        if result.uncovered_scoring_count > 0 and result.passed:
            result.passed = False
            result.risk_level = "中" if result.risk_level == "低" else result.risk_level
            result.issues.insert(
                0,
                ComplianceIssue(
                    severity="高",
                    category="评分覆盖",
                    message=f"有 {result.uncovered_scoring_count} 项评分要求未在目录中体现",
                    suggestion="在目录编辑中补充对应章节，或使用「一一对应」模式重新生成目录",
                ),
            )

        leaves = [x for x in outline_summary if not x.get("has_content")]
        if len(leaves) > 0:
            result.issues.append(
                ComplianceIssue(
                    severity="中",
                    category="章节缺失",
                    message=f"仍有 {len(leaves)} 个末级章节未生成正文",
                    suggestion="在正文编辑页批量生成或手工补全",
                )
            )
            if len(leaves) > len(outline_summary) * 0.3:
                result.passed = False
                result.risk_level = "高"

        if not result.summary:
            result.summary = (
                "合规检查完成"
                if result.passed
                else "存在需处理的问题，请查看明细"
            )
        return result
