"""Word 导出服务。

版式参考国内常见投标文件习惯（A4、页边距、宋体层级、段前段后、行距等），
常量集中在下方，可按招标方要求自行微调。

说明：部分 Word/WPS 会弱化对「样式表」的展示，故对标题与正文在「段落/Run」
上同时写入显式格式，保证导出即可见首行缩进、小四、1.5 倍行距等。
"""

import io
import logging
import os
import re
from urllib.parse import quote

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from ..models.schemas import WordExportOutlineItem, WordExportRequest
from ..services.localdb_image_service import (
    list_company_extracted_images,
    pick_images_for_chapter,
)
from ..utils.localdb_paths import localdb_template_exists, localdb_template_path, sanitize_company_id

# ----- 正文 -----
BODY_FONT_SIZE = Pt(12)  # 小四
BODY_FIRST_LINE_INDENT = Pt(24)  # 首行缩进约两个汉字（12pt×2）
BODY_PARA_SPACE_AFTER = Pt(6)

# ----- 纸张与页边距（A4，装订侧略大） -----
PAGE_TOP_MARGIN = Cm(2.54)
PAGE_BOTTOM_MARGIN = Cm(2.54)
PAGE_LEFT_MARGIN = Cm(3.0)
PAGE_RIGHT_MARGIN = Cm(2.5)

# ----- 封面主标题 -----
COVER_TITLE_FONT_SIZE = Pt(22)  # 二号
COVER_TITLE_SPACE_BEFORE = Pt(24)
COVER_TITLE_SPACE_AFTER = Pt(18)

# ----- 样式：一级～三级标题（宋体加粗，字号递减） -----
HEADING1_FONT_SIZE = Pt(15)  # 小三
HEADING1_SPACE_BEFORE = Pt(12)
HEADING1_SPACE_AFTER = Pt(6)

HEADING2_FONT_SIZE = Pt(14)  # 四号
HEADING2_SPACE_BEFORE = Pt(6)
HEADING2_SPACE_AFTER = Pt(3)

HEADING3_FONT_SIZE = Pt(12)  # 小四（与正文同号，靠加粗区分）
HEADING3_SPACE_BEFORE = Pt(3)
HEADING3_SPACE_AFTER = Pt(3)

# 标题/正文行距：用 MULTIPLE 1.5，兼容性优于枚举 ONE_POINT_FIVE
LINE_SPACING_MULTIPLE = 1.5

logger = logging.getLogger(__name__)

# ----- 大纲四级及以下标题（仍用正文号加粗） -----
SUB_OUTLINE_HEADING_SPACE_BEFORE = Pt(6)
SUB_OUTLINE_HEADING_SPACE_AFTER = Pt(3)

# ----- 列表（正文级，左侧略缩进） -----
LIST_LEFT_INDENT = Cm(0.63)


def _set_run_font_simsun(run: docx.text.run.Run) -> None:
    run.font.name = "宋体"
    rpr = run._element.rPr
    if rpr is not None and rpr.rFonts is not None:
        rpr.rFonts.set(qn("w:eastAsia"), "宋体")


def _set_paragraph_font_simsun(paragraph: docx.text.paragraph.Paragraph) -> None:
    for run in paragraph.runs:
        _set_run_font_simsun(run)


def _set_line_spacing_1_5(pf) -> None:
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = LINE_SPACING_MULTIPLE


def _format_body_paragraph(
    paragraph: docx.text.paragraph.Paragraph,
    *,
    first_line_indent_two_chars: bool = True,
) -> None:
    """宋体小四、1.5 倍行距；可选首行缩进两个字符（显式写入段落，不依赖样式）。"""
    pf = paragraph.paragraph_format
    _set_line_spacing_1_5(pf)
    if first_line_indent_two_chars:
        pf.first_line_indent = BODY_FIRST_LINE_INDENT
    for run in paragraph.runs:
        _set_run_font_simsun(run)
        run.font.size = BODY_FONT_SIZE


def _apply_heading_level_direct(
    paragraph: docx.text.paragraph.Paragraph, level: int
) -> None:
    """对 add_heading 产生的段落强制字号/行距/段距，避免 Word 忽略样式表修改。"""
    lv = max(1, min(3, level))
    sizes = {
        1: HEADING1_FONT_SIZE,
        2: HEADING2_FONT_SIZE,
        3: HEADING3_FONT_SIZE,
    }
    before = {
        1: HEADING1_SPACE_BEFORE,
        2: HEADING2_SPACE_BEFORE,
        3: HEADING3_SPACE_BEFORE,
    }
    after = {
        1: HEADING1_SPACE_AFTER,
        2: HEADING2_SPACE_AFTER,
        3: HEADING3_SPACE_AFTER,
    }
    pt_size = sizes[lv]
    pf = paragraph.paragraph_format
    pf.space_before = before[lv]
    pf.space_after = after[lv]
    _set_line_spacing_1_5(pf)
    pf.widow_control = True
    pf.keep_with_next = True
    for run in paragraph.runs:
        _set_run_font_simsun(run)
        run.font.bold = True
        run.font.size = pt_size


def _polish_heading_paragraph(paragraph: docx.text.paragraph.Paragraph) -> None:
    """标题与后续段落不分页孤立。"""
    pf = paragraph.paragraph_format
    pf.widow_control = True
    pf.keep_with_next = True


def _style_rfonts_simsun(style) -> None:
    if style._element.rPr is None:
        style._element._add_rPr()
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


class WordExportService:
    """负责将目录数据导出为 Word 文档。"""

    @staticmethod
    def _resolve_company_template(company_id: str | None) -> str | None:
        if not company_id:
            return None
        try:
            cid = sanitize_company_id(company_id)
        except ValueError:
            return None
        if localdb_template_exists(cid):
            return localdb_template_path(cid)
        return None

    @staticmethod
    def _create_document_from_template(template_path: str | None) -> docx.Document:
        if template_path and os.path.isfile(template_path):
            return docx.Document(template_path)
        return docx.Document()

    @staticmethod
    def _append_content_start(doc: docx.Document, use_template: bool) -> None:
        """在模板正文后分页，再写入生成内容。"""
        if not use_template:
            return
        try:
            doc.add_page_break()
        except Exception:
            logger.exception("Word 导出：模板后分页失败")

    @staticmethod
    def export_outline(request: WordExportRequest) -> tuple[io.BytesIO, dict[str, str]]:
        template_path = WordExportService._resolve_company_template(
            request.localdb_company_id
        )
        use_template = bool(template_path)
        doc = WordExportService._create_document_from_template(template_path)

        if not use_template:
            WordExportService._apply_bid_document_page_setup(doc)
        WordExportService._init_document_styles(doc)

        if not use_template:
            WordExportService._add_document_intro(
                doc, request.project_name, request.project_overview
            )
        else:
            WordExportService._append_content_start(doc, use_template=True)
            if request.project_overview and request.project_overview.strip():
                heading = doc.add_heading("项目概述", level=1)
                heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
                _apply_heading_level_direct(heading, 1)
                _polish_heading_paragraph(heading)
                overview_paragraph = doc.add_paragraph(request.project_overview)
                _set_paragraph_font_simsun(overview_paragraph)
                _format_body_paragraph(overview_paragraph, first_line_indent_two_chars=True)
                overview_paragraph.paragraph_format.space_after = Pt(12)

        image_assets = []
        if request.insert_localdb_images and request.localdb_company_id:
            try:
                cid = sanitize_company_id(request.localdb_company_id or "default")
                image_assets = list_company_extracted_images(cid)
            except ValueError:
                image_assets = []

        WordExportService._add_outline_items(
            doc,
            request.outline,
            image_assets=image_assets,
            max_images_per_chapter=request.max_images_per_chapter,
        )

        if request.include_appendices and request.localdb_company_id:
            WordExportService._append_filled_appendices(
                doc,
                request.localdb_company_id,
                request.project_name,
                request.appendix_template_names,
            )

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        filename = f"{request.project_name or '标书文档'}.docx"
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        }
        return buffer, headers

    @staticmethod
    def _apply_bid_document_page_setup(doc: docx.Document) -> None:
        """A4 纸张、常用页边距（左侧略大便于装订）。"""
        try:
            for section in doc.sections:
                section.top_margin = PAGE_TOP_MARGIN
                section.bottom_margin = PAGE_BOTTOM_MARGIN
                section.left_margin = PAGE_LEFT_MARGIN
                section.right_margin = PAGE_RIGHT_MARGIN
        except Exception:
            logger.exception("Word 导出：设置页边距失败，将使用模板默认边距")

    @staticmethod
    def _init_document_styles(doc: docx.Document) -> None:
        """统一宋体与标题层级（样式表）；单条失败不影响其余。"""
        styles = doc.styles

        if "Normal" in styles:
            try:
                style = styles["Normal"]
                style.font.name = "宋体"
                _style_rfonts_simsun(style)
                style.font.bold = False
                style.font.size = BODY_FONT_SIZE
                _set_line_spacing_1_5(style.paragraph_format)
            except Exception:
                logger.exception("Word 导出：设置 Normal 样式失败")

        heading_specs: list[tuple[str, Pt, Pt, Pt]] = [
            (
                "Heading 1",
                HEADING1_FONT_SIZE,
                HEADING1_SPACE_BEFORE,
                HEADING1_SPACE_AFTER,
            ),
            (
                "Heading 2",
                HEADING2_FONT_SIZE,
                HEADING2_SPACE_BEFORE,
                HEADING2_SPACE_AFTER,
            ),
            (
                "Heading 3",
                HEADING3_FONT_SIZE,
                HEADING3_SPACE_BEFORE,
                HEADING3_SPACE_AFTER,
            ),
        ]
        for style_name, pt_size, space_before, space_after in heading_specs:
            if style_name not in styles:
                continue
            try:
                style = styles[style_name]
                style.font.name = "宋体"
                _style_rfonts_simsun(style)
                style.font.bold = True
                style.font.size = pt_size
                pf = style.paragraph_format
                pf.space_before = space_before
                pf.space_after = space_after
                _set_line_spacing_1_5(pf)
                pf.widow_control = True
                pf.keep_with_next = True
            except Exception:
                logger.exception("Word 导出：设置 %s 样式失败", style_name)

        if "Title" in styles:
            try:
                style = styles["Title"]
                style.font.name = "宋体"
                _style_rfonts_simsun(style)
                style.font.bold = True
                style.font.size = COVER_TITLE_FONT_SIZE
            except Exception:
                logger.exception("Word 导出：设置 Title 样式失败")

    @staticmethod
    def _add_document_intro(
        doc: docx.Document, project_name: str | None, project_overview: str | None
    ) -> None:
        title_paragraph = doc.add_paragraph()
        tpf = title_paragraph.paragraph_format
        tpf.space_before = COVER_TITLE_SPACE_BEFORE
        tpf.space_after = COVER_TITLE_SPACE_AFTER
        title_run = title_paragraph.add_run(project_name or "投标技术文件")
        title_run.bold = True
        title_run.font.size = COVER_TITLE_FONT_SIZE
        _set_run_font_simsun(title_run)
        title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

        if project_overview:
            heading = doc.add_heading("项目概述", level=1)
            heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _apply_heading_level_direct(heading, 1)
            _polish_heading_paragraph(heading)
            overview_paragraph = doc.add_paragraph(project_overview)
            _set_paragraph_font_simsun(overview_paragraph)
            _format_body_paragraph(overview_paragraph, first_line_indent_two_chars=True)
            overview_paragraph.paragraph_format.space_after = Pt(12)

    @staticmethod
    def _add_markdown_runs(para: docx.text.paragraph.Paragraph, text: str) -> None:
        pattern = r"(\*\*.*?\*\*|\*.*?\*|`.*?`)"
        parts = re.split(pattern, text)
        for part in parts:
            if not part:
                continue
            run = para.add_run()
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                run.text = part[2:-2]
                run.bold = True
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                run.text = part[1:-1]
                run.italic = True
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                run.text = part[1:-1]
            else:
                run.text = part
            _set_run_font_simsun(run)

    @staticmethod
    def _add_markdown_paragraph(doc: docx.Document, text: str) -> None:
        para = doc.add_paragraph()
        WordExportService._add_markdown_runs(para, text)
        _format_body_paragraph(para, first_line_indent_two_chars=True)
        para.paragraph_format.space_after = BODY_PARA_SPACE_AFTER

    @staticmethod
    def _parse_markdown_blocks(content: str) -> list[tuple]:
        blocks: list[tuple] = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].rstrip("\r").strip()
            if not line:
                i += 1
                continue

            if (
                line.startswith("- ")
                or line.startswith("* ")
                or re.match(r"^\d+\.\s", line)
            ):
                items: list[tuple] = []
                while i < len(lines):
                    raw = lines[i].rstrip("\r")
                    stripped = raw.strip()
                    if stripped.startswith("- ") or stripped.startswith("* "):
                        text = re.sub(r"^[-*]\s+", "", stripped).strip()
                        if text:
                            items.append(("unordered", None, text))
                        i += 1
                        continue
                    match_number = re.match(r"^(\d+)\.\s+(.*)$", stripped)
                    if match_number:
                        num_str, text = match_number.groups()
                        if text.strip():
                            items.append(("ordered", num_str, text.strip()))
                        i += 1
                        continue
                    break
                if items:
                    blocks.append(("list", items))
                continue

            if "|" in line:
                rows: list[str] = []
                while i < len(lines):
                    stripped = lines[i].rstrip("\r").strip()
                    if "|" not in stripped:
                        break
                    if not re.match(r"^\|?[-\s\|]+\|?$", stripped):
                        cells = [cell.strip() for cell in stripped.split("|")]
                        row_text = " | ".join([cell for cell in cells if cell])
                        if row_text:
                            rows.append(row_text)
                    i += 1
                if rows:
                    blocks.append(("table", rows))
                continue

            if line.startswith("#"):
                match_heading = re.match(r"^(#+)\s*(.*)$", line)
                if match_heading:
                    level_marks, title_text = match_heading.groups()
                    blocks.append(
                        ("heading", min(len(level_marks), 3), title_text.strip())
                    )
                i += 1
                continue

            para_lines: list[str] = []
            while i < len(lines):
                stripped = lines[i].rstrip("\r").strip()
                if (
                    stripped
                    and not stripped.startswith("-")
                    and not stripped.startswith("*")
                    and "|" not in stripped
                    and not stripped.startswith("#")
                ):
                    para_lines.append(stripped)
                    i += 1
                else:
                    break
            if para_lines:
                blocks.append(("paragraph", " ".join(para_lines)))
            else:
                i += 1

        return blocks

    @staticmethod
    def _render_markdown_blocks(doc: docx.Document, blocks: list[tuple]) -> None:
        for block in blocks:
            kind = block[0]
            if kind == "list":
                for item_kind, num_str, text in block[1]:
                    paragraph = doc.add_paragraph()
                    prefix = "• " if item_kind == "unordered" else f"{num_str}. "
                    run = paragraph.add_run(prefix)
                    _set_run_font_simsun(run)
                    WordExportService._add_markdown_runs(paragraph, text)
                    _format_body_paragraph(
                        paragraph, first_line_indent_two_chars=False
                    )
                    paragraph.paragraph_format.left_indent = LIST_LEFT_INDENT
            elif kind == "table":
                for row in block[1]:
                    WordExportService._add_markdown_paragraph(doc, row)
            elif kind == "heading":
                _, level, text = block
                heading = doc.add_heading(text, level=level)
                heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
                _apply_heading_level_direct(heading, level)
                _polish_heading_paragraph(heading)
            elif kind == "paragraph":
                WordExportService._add_markdown_paragraph(doc, block[1])

    @staticmethod
    def _add_markdown_content(doc: docx.Document, content: str) -> None:
        blocks = WordExportService._parse_markdown_blocks(content)
        WordExportService._render_markdown_blocks(doc, blocks)

    @staticmethod
    def _append_filled_appendices(
        doc: docx.Document,
        company_id: str | None,
        project_name: str | None,
        template_names: list[str] | None,
    ) -> None:
        import tempfile
        import os
        from .appendix_service import (
            appendix_root,
            build_placeholder_map,
            ensure_default_templates,
            fill_docx_template,
        )
        from ..utils.localdb_paths import sanitize_company_id

        try:
            cid = sanitize_company_id(company_id or "default")
        except ValueError:
            return
        ensure_default_templates(cid)
        root = appendix_root(cid)
        mapping = build_placeholder_map(cid, project_name=project_name)
        names = template_names or [
            fn for fn in os.listdir(root) if fn.lower().endswith(".docx")
        ]
        work = tempfile.mkdtemp(prefix="appendix_merge_")
        paths: list[str] = []
        try:
            for fn in names:
                src = os.path.join(root, fn)
                if not os.path.isfile(src):
                    continue
                dst = os.path.join(work, fn)
                fill_docx_template(src, dst, mapping)
                paths.append(dst)
            if paths:
                from .appendix_service import append_docx_files_to_document

                append_docx_files_to_document(doc, paths)
        finally:
            import shutil

            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _append_chapter_images(
        doc: docx.Document,
        chapter_title: str,
        chapter_description: str | None,
        image_assets: list,
        max_images: int,
    ) -> None:
        if not image_assets or max_images <= 0:
            return
        picked = pick_images_for_chapter(
            chapter_title,
            chapter_description or "",
            image_assets,
            max_images=max_images,
        )
        if not picked:
            return
        cap = doc.add_paragraph()
        cap_run = cap.add_run("（以下附图来自公司本地库资料）")
        _set_run_font_simsun(cap_run)
        cap_run.font.size = Pt(10)
        cap_run.italic = True
        for asset in picked:
            try:
                doc.add_paragraph()
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = para.add_run()
                run.add_picture(asset.abs_path, width=Cm(14))
                note = doc.add_paragraph()
                note_run = note.add_run(
                    f"图：{asset.source_file} / {asset.image_name}"
                )
                _set_run_font_simsun(note_run)
                note_run.font.size = Pt(9)
                note.alignment = WD_ALIGN_PARAGRAPH.CENTER
            except Exception:
                logger.exception("插入图片失败: %s", asset.abs_path)

    @staticmethod
    def _add_outline_items(
        doc: docx.Document,
        items: list[WordExportOutlineItem],
        level: int = 1,
        *,
        image_assets: list | None = None,
        max_images_per_chapter: int = 4,
    ) -> None:
        assets = image_assets or []
        for item in items:
            if level <= 3:
                heading = doc.add_heading(f"{item.id} {item.title}", level=level)
                heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
                _apply_heading_level_direct(heading, level)
                _polish_heading_paragraph(heading)
            else:
                para = doc.add_paragraph()
                run = para.add_run(f"{item.id} {item.title}")
                run.bold = True
                _set_run_font_simsun(run)
                run.font.size = BODY_FONT_SIZE
                pf = para.paragraph_format
                _set_line_spacing_1_5(pf)
                pf.space_before = SUB_OUTLINE_HEADING_SPACE_BEFORE
                pf.space_after = SUB_OUTLINE_HEADING_SPACE_AFTER
                pf.widow_control = True
                pf.keep_with_next = True

            if not item.children:
                content = item.content or ""
                if content.strip():
                    WordExportService._add_markdown_content(doc, content)
                if assets:
                    WordExportService._append_chapter_images(
                        doc,
                        item.title,
                        item.description,
                        assets,
                        max_images_per_chapter,
                    )
                continue

            WordExportService._add_outline_items(
                doc,
                item.children,
                level + 1,
                image_assets=assets,
                max_images_per_chapter=max_images_per_chapter,
            )
