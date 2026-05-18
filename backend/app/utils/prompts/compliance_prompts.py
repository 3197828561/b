"""标书合规终检提示词。"""

import json
from typing import Any


def build_compliance_check_messages(
    project_overview: str,
    tech_requirements: str,
    scoring_groups: list[dict[str, Any]],
    outline_summary: list[dict[str, Any]],
) -> list[dict[str, str]]:
    scoring_json = json.dumps(scoring_groups, ensure_ascii=False, indent=2)
    outline_json = json.dumps(outline_summary, ensure_ascii=False, indent=2)

    system = """你是投标文件合规审查专家。根据招标要求、评分项与目录/章节摘要，输出 JSON：
{
  "passed": true/false,
  "risk_level": "低|中|高",
  "summary": "一句话总结",
  "issues": [
    {
      "severity": "高|中|低",
      "category": "评分覆盖|章节缺失|内容风险|格式建议",
      "message": "问题描述",
      "suggestion": "修改建议"
    }
  ]
}
只输出 JSON，不要 markdown。"""

    user = f"""## 项目概述
{project_overview[:4000]}

## 技术评分要求
{tech_requirements[:6000]}

## 评分项（JSON）
{scoring_json[:8000]}

## 目录末级章节摘要（JSON，含是否已有正文）
{outline_json[:12000]}

请检查：评分项是否在目录中有对应章节；关键章节是否缺少正文；是否存在明显废标风险表述（如未响应、待填写占位过多）。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
