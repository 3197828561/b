"""正文生成相关提示词。"""

import hashlib
from typing import Any, Dict, List


def diversity_temperature(base: float, company_id: str, chapter_id: str) -> float:
    """
    在稳定区间内按「公司 + 章节」微调温度，使不同投标主体、不同章节的措辞分布有差异。
    """
    raw = hashlib.sha256(f"{company_id or 'default'}\0{chapter_id}".encode()).hexdigest()
    n = int(raw[:8], 16)
    offset = (n % 13) / 100.0  # 0.00～0.12
    t = base - 0.05 + offset
    return max(0.58, min(0.88, round(t, 3)))


def _writing_emphasis_nudge(company_id: str, chapter_id: str) -> str:
    """按主体与章节稳定轮换写作侧重点，降低跨公司文本同质化。"""
    raw = hashlib.sha256(f"nudge\0{company_id or 'default'}\0{chapter_id}".encode()).hexdigest()
    idx = int(raw[:8], 16) % 5
    variants = [
        "本节可适当加入可量化指标、时间节点或检查频次，少用空洞承诺。",
        "本节侧重写清岗位/班组职责、接口与移交条件，避免与其它章节口号重复。",
        "本节宜按实施流程分步叙述（准备—实施—验收），突出可执行细节。",
        "本节可穿插质量、安全或环保控制要点，与同级章节形成不同侧重点。",
        "本节宜结合资源配置与风险预案，用具体措施代替泛化表述。",
    ]
    return variants[idx]


def build_chapter_content_messages(
    chapter: Dict[str, Any],
    parent_chapters: List[Dict[str, Any]] | None = None,
    sibling_chapters: List[Dict[str, Any]] | None = None,
    project_overview: str = "",
    reference_materials: List[str] | None = None,
    chapter_word_count_min: int = 800,
    chapter_word_count_max: int = 2500,
    book_word_count_min: int | None = None,
    book_word_count_max: int | None = None,
    leaf_chapter_index: int | None = None,
    leaf_chapter_total: int | None = None,
    company_display_name: str = "",
    localdb_company_id: str = "",
) -> List[Dict[str, str]]:
    """构建章节正文生成消息。"""
    chapter_id = str(chapter.get("id", "unknown"))
    chapter_title = chapter.get("title", "未命名章节")
    chapter_description = chapter.get("description", "")

    identity = (company_display_name or "").strip() or (
        (localdb_company_id or "").strip() if (localdb_company_id or "").strip() != "default" else ""
    )
    cid_for_hash = (localdb_company_id or "default").strip() or "default"

    lo = max(50, int(chapter_word_count_min))
    hi = max(lo, int(chapter_word_count_max))

    book_scope = ""
    if (
        book_word_count_min is not None
        and book_word_count_max is not None
        and leaf_chapter_index is not None
        and leaf_chapter_total is not None
    ):
        bm, bx = int(book_word_count_min), int(book_word_count_max)
        k, n = int(leaf_chapter_index), int(leaf_chapter_total)
        book_scope = f"""
8. 全书体量（重要）：全部末级章节正文合计，目标总字数约 {bm}～{bx} 字（字符计，与第 6 条计数方式一致）。当前为全部 {n} 个末级章节中的第 {k} 章；请在满足本章约 {lo}～{hi} 字的同时，与其他章节协调，避免单章无故畸长畸短，使全书总篇幅大致落在上述全书目标区间。
"""

    identity_rules = ""
    if identity:
        identity_rules = f"""
9. 投标主体与差异性（极其重要）：本章正文须专门为投标主体「{identity}」撰写。全文须自然体现该主体（可合理使用「我公司」「本单位」等与主体名称交替），所有措施、组织、业绩与资源均须落在该主体上。
10. 禁止与其它投标主体「可互换」：即使招标文件与项目背景相同，也不得输出可原样套用到另一家公司的通用模板段；禁止大段与其它潜在投标人无差别的口号式排比。须结合下方参考资料（若有）与主体名称，在技术路线、组织与人员、机具与材料、质量安全、进度与接口、服务与售后等方面写出该主体语境下的自有表述。
11. 若参考资料较少或检索片段相关性弱，仍须依据章节主题与主体「{identity}」做合理、具体、可区分的展开，从结构层次、用词与小标题上与「未指定主体的泛泛技术说明」拉开差距。
"""

    system_prompt = f"""你是一个专业的标书编写专家，负责为投标文件的技术标部分生成具体内容。

要求：
1. 内容要专业、准确，与章节标题和描述保持一致。
2. 这是技术方案，不是宣传报告，注意朴实无华，不要假大空。
3. 语言要正式、规范，符合标书写作要求，但不要使用奇怪的连接词，不要让人觉得内容像是 AI 生成的。
4. 内容要详细具体，避免空泛的描述。
5. 注意避免与同级章节内容重复，保持内容的独特性和互补性。
6. 篇幅（重要）：本章正文（不含章节标题行、不含列表外的说明性套话）请控制在约 {lo}～{hi} 字之间；以中文标书常见习惯按字符数理解（汉字、字母、数字、标点均计入），优先落在该区间内，明显短于下限或明显超过上限均不符合要求。
7. 直接返回章节内容，不生成标题，不要任何额外说明或格式标记。{book_scope}{identity_rules}
"""

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]

    if identity:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"【投标主体】{identity}\n"
                    "以下生成的正文必须专属于上述主体，不得写成可适用于任意投标单位的通用稿。"
                ),
            }
        )

    if project_overview.strip():
        messages.append(
            {"role": "user", "content": f"项目概述信息：\n{project_overview}"}
        )

    if reference_materials and len(reference_materials) > 0:
        # 把本地数据库资料作为“参考资料”注入提示词
        joined_refs = "\n\n".join(reference_materials)
        messages.append(
            {
                "role": "user",
                "content": f"参考资料（来自当前投标主体在本地库中的材料，优先用于事实/表述/适用性）：\n{joined_refs}\n\n请务必结合参考资料生成章节正文内容；与主体无关的片段请勿硬套。",
            }
        )
    elif identity:
        messages.append(
            {
                "role": "user",
                "content": (
                    f"【说明】当前投标主体「{identity}」的本地资料库中，与本章检索词直接匹配的片段较少或为空。"
                    "请仍须以该主体为第一视角撰写，通过具体措施、合理假设与可执行安排体现主体特色，避免与其它公司可共用的空话。"
                ),
            }
        )

    if parent_chapters:
        parent_lines = ["上级章节信息："]
        for parent in parent_chapters:
            parent_lines.append(
                f"- {parent.get('id', 'unknown')} {parent.get('title', '未命名章节')}\n  {parent.get('description', '')}"
            )
        messages.append({"role": "user", "content": "\n".join(parent_lines)})

    if sibling_chapters:
        sibling_lines = ["同级章节信息（请避免内容重复）："]
        for sibling in sibling_chapters:
            if sibling.get("id") == chapter_id:
                continue
            sibling_lines.append(
                f"- {sibling.get('id', 'unknown')} {sibling.get('title', '未命名章节')}\n  {sibling.get('description', '')}"
            )
        if len(sibling_lines) > 1:
            messages.append({"role": "user", "content": "\n".join(sibling_lines)})

    book_user_note = ""
    if (
        book_word_count_min is not None
        and book_word_count_max is not None
        and leaf_chapter_total is not None
        and leaf_chapter_index is not None
    ):
        book_user_note = (
            f"\n全书末级章节共 {int(leaf_chapter_total)} 章，当前为第 {int(leaf_chapter_index)} 章；"
            f"全书正文合计目标约 {int(book_word_count_min)}～{int(book_word_count_max)} 字，请兼顾全书体量。"
        )

    nudge = _writing_emphasis_nudge(cid_for_hash, chapter_id)
    identity_line = (
        f"\n投标主体：{identity}（全文须与该主体强绑定）。\n" if identity else ""
    )

    chapter_user_content = f"""请为以下标书章节生成具体内容：

当前章节信息：
章节ID: {chapter_id}
章节标题: {chapter_title}
章节描述: {chapter_description}
{identity_line}
请根据项目概述信息和上述章节层级关系，生成详细的专业内容，确保与上级章节的内容逻辑相承，同时避免与同级章节内容重复，突出本章节的独特性和技术方案优势。
写作提示（按主体与章节轮换，请自然融入正文，不要单独成段复述本句）：{nudge}
本章正文字数请控制在约 {lo}～{hi} 字（字符计）范围内。{book_user_note}
直接返回编写的正文内容，不要输出标题、解释、总结等任何其他内容"""

    messages.append({"role": "user", "content": chapter_user_content})

    return messages
