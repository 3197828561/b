"""技术评分项与目录覆盖检查（无需调用模型）。"""

from __future__ import annotations

import re
from typing import Any


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    lower = text.lower()
    words = set(re.findall(r"[a-z0-9]+", lower))
    han = set(re.findall(r"[\u4e00-\u9fff]", text))
    # 2+ 字中文词组（粗略）
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if re.match(r"[\u4e00-\u9fff]{2}", pair):
            han.add(pair)
    return words | han


def _collect_leaves(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaves: list[dict[str, Any]] = []
    for item in items:
        children = item.get("children") or []
        if children:
            leaves.extend(_collect_leaves(children))
        else:
            leaves.append(item)
    return leaves


def _leaf_covers_group(leaf: dict[str, Any], group: dict[str, Any]) -> bool:
    rid = str(group.get("requirement_id") or "").strip()
    gtitle = str(group.get("title") or "").strip()
    if not gtitle and not rid:
        return False

    leaf_rid = str(leaf.get("source_requirement_id") or "").strip()
    if rid and leaf_rid and rid == leaf_rid:
        return True

    leaf_title = str(leaf.get("title") or "")
    leaf_desc = str(leaf.get("description") or "")
    leaf_src = str(leaf.get("source_requirement_title") or "")
    blob = f"{leaf_title} {leaf_desc} {leaf_src}"
    g_tokens = _tokenize(gtitle)
    if not g_tokens:
        return False
    l_tokens = _tokenize(blob)
    overlap = g_tokens.intersection(l_tokens)
    # 标题较长时至少 2 个 token 重合，短标题 1 个即可
    need = 2 if len(g_tokens) >= 4 else 1
    return len(overlap) >= need


def check_scoring_coverage(
    groups: list[dict[str, Any]],
    outline: list[dict[str, Any]],
) -> dict[str, Any]:
    """返回覆盖统计与未覆盖评分项列表。"""
    if not groups:
        return {
            "total": 0,
            "covered_count": 0,
            "uncovered_count": 0,
            "coverage_rate": 1.0,
            "covered": [],
            "uncovered": [],
            "leaf_count": len(_collect_leaves(outline)),
        }

    leaves = _collect_leaves(outline)
    covered: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []

    for group in groups:
        if any(_leaf_covers_group(leaf, group) for leaf in leaves):
            covered.append(group)
        else:
            uncovered.append(group)

    total = len(groups)
    covered_count = len(covered)
    rate = covered_count / total if total else 1.0

    return {
        "total": total,
        "covered_count": covered_count,
        "uncovered_count": len(uncovered),
        "coverage_rate": round(rate, 4),
        "covered": covered,
        "uncovered": uncovered,
        "leaf_count": len(leaves),
    }
