"""扫描件 OCR：为本地库 RAG 补充可检索文本（依赖 rapidocr-onnxruntime，可选）。"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

_ocr_engine = None
_ocr_probe_done = False
_ocr_available = False


@dataclass
class OcrSupplementResult:
    text: str
    applied: bool
    source: str  # none / pdf_pages / docx_images / docx_embedded
    attempted: bool = False
    units_processed: int = 0
    units_total: int = 0
    ocr_char_count: int = 0
    embedded_images_saved: int = 0


def is_ocr_available() -> bool:
    """是否已安装并可初始化 RapidOCR。"""
    global _ocr_probe_done, _ocr_available
    if _ocr_probe_done:
        return _ocr_available
    if not settings.ocr_enabled:
        _ocr_probe_done = True
        _ocr_available = False
        return False
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: F401

        _ocr_available = True
    except ImportError:
        logger.warning(
            "未安装 rapidocr-onnxruntime，扫描件 OCR 不可用。"
            "请执行: pip install rapidocr-onnxruntime"
        )
        _ocr_available = False
    _ocr_probe_done = True
    return _ocr_available


def _get_engine():
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    from rapidocr_onnxruntime import RapidOCR

    _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_numpy_image(arr) -> str:
    engine = _get_engine()
    result, _ = engine(arr)
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        if not item or len(item) < 2:
            continue
        text = str(item[1]).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _ocr_image_bytes(img_data: bytes) -> str:
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return ""

    try:
        with Image.open(io.BytesIO(img_data)) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            arr = np.array(img)
        return _ocr_numpy_image(arr)
    except Exception as exc:
        logger.debug("单张图片 OCR 失败: %s", exc)
        return ""


def should_supplement_with_ocr(base_text: str, file_size_bytes: int) -> bool:
    """文本过少且文件偏大时，判定为扫描件并触发 OCR。"""
    if not settings.ocr_enabled:
        return False
    if file_size_bytes < settings.ocr_min_file_bytes:
        return False

    stripped = (base_text or "").strip()
    char_count = len(stripped)

    if char_count >= settings.ocr_skip_if_chars_ge:
        return False

    if char_count < settings.ocr_trigger_max_chars:
        return True

    # 大文件但正文仍偏少（典型：多页扫描 PDF/Word）
    if (
        file_size_bytes >= settings.ocr_large_file_bytes
        and char_count < settings.ocr_large_file_min_chars
    ):
        return True

    return False


def _ocr_pdf_sync(file_path: str) -> tuple[str, int, int]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "", 0, 0

    parts: list[str] = []
    doc = fitz.open(file_path)
    try:
        total = len(doc)
        limit = min(total, settings.ocr_pdf_max_pages)
        matrix = fitz.Matrix(settings.ocr_pdf_zoom, settings.ocr_pdf_zoom)
        for i in range(limit):
            page = doc[i]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_bytes = pix.tobytes("png")
            page_text = _ocr_image_bytes(img_bytes)
            if page_text.strip():
                parts.append(f"--- 第{i + 1}页 OCR ---\n{page_text}")
        return "\n\n".join(parts), limit, total
    finally:
        doc.close()


def _ocr_docx_sync(file_path: str) -> tuple[str, int, int]:
    from .file_service import FileService

    images = FileService.extract_images_from_docx(file_path)
    total = len(images)
    limit = min(total, settings.ocr_docx_max_images)
    parts: list[str] = []
    for img_data, _ext, img_index in images[:limit]:
        page_text = _ocr_image_bytes(img_data)
        if page_text.strip():
            parts.append(f"--- 图片{img_index} OCR ---\n{page_text}")
    return "\n\n".join(parts), limit, total


def _merge_ocr_results(
    primary: OcrSupplementResult, extra: OcrSupplementResult
) -> OcrSupplementResult:
    if not extra.embedded_images_saved and not extra.applied:
        return primary
    return OcrSupplementResult(
        text=extra.text,
        applied=primary.applied or extra.applied,
        source=extra.source if extra.applied else primary.source,
        attempted=primary.attempted or extra.attempted,
        units_processed=primary.units_processed + extra.units_processed,
        units_total=max(primary.units_total, extra.units_total),
        ocr_char_count=primary.ocr_char_count + extra.ocr_char_count,
        embedded_images_saved=extra.embedded_images_saved,
    )


def _supplement_embedded_docx_sync(
    file_path: str,
    company_id: str,
    source_filename: str,
    base_text: str,
) -> OcrSupplementResult:
    """导出 Word 内嵌图到本地库，并 OCR 写入可检索文本（不受正文长度限制）。"""
    from .file_service import FileService

    combined = (base_text or "").strip()
    if not settings.ocr_docx_embedded_always:
        return OcrSupplementResult(text=combined, applied=False, source="none")

    images = FileService.extract_images_from_docx(file_path)
    total = len(images)
    if total == 0:
        return OcrSupplementResult(text=combined, applied=False, source="none")

    limit = min(total, settings.ocr_docx_max_images)
    saved = FileService.save_localdb_extracted_images(
        company_id, source_filename, images[:limit]
    )
    rel_dir = os.path.dirname(saved[0][0]) if saved else "_extracted"
    parts: list[str] = [
        f"--- 文档内嵌图片（共 {total} 张，已导出 {len(saved)} 张至 {rel_dir}/） ---"
    ]
    ocr_chars = 0
    ocr_used = 0
    ocr_ok = is_ocr_available()

    for rel_path, img_index, img_data in saved:
        parts.append(f"[图片{img_index}] 原图：{rel_path}")
        if ocr_ok:
            page_text = _ocr_image_bytes(img_data)
            if page_text.strip():
                parts.append(f"[图片{img_index} OCR]\n{page_text}")
                ocr_chars += len(page_text)
                ocr_used += 1
            else:
                parts.append(f"[图片{img_index}]（未识别到文字，请查看原图）")
        else:
            parts.append(f"[图片{img_index}]（请查看原图；安装 OCR 后可识别图中文字）")

    block = "\n".join(parts).strip()
    merged = combined
    if merged:
        merged += "\n\n"
    merged += block

    return OcrSupplementResult(
        text=merged,
        applied=ocr_used > 0,
        source="docx_embedded",
        attempted=True,
        units_processed=len(saved),
        units_total=total,
        ocr_char_count=ocr_chars,
        embedded_images_saved=len(saved),
    )


async def supplement_embedded_docx_images(
    file_path: str,
    company_id: str,
    source_filename: str,
    base_text: str,
) -> OcrSupplementResult:
    try:
        return await asyncio.to_thread(
            _supplement_embedded_docx_sync,
            file_path,
            company_id,
            source_filename,
            base_text,
        )
    except Exception as exc:
        logger.exception("内嵌图片处理失败: %s", exc)
        return OcrSupplementResult(
            text=(base_text or "").strip(),
            applied=False,
            source="none",
            attempted=True,
        )


async def supplement_document_text(
    file_path: str,
    doc_kind: str,
    base_text: str,
    file_size_bytes: int,
) -> OcrSupplementResult:
    """
    在已有抽取文本基础上，按需对 PDF 逐页或 DOCX 内嵌图做 OCR 补充。
  """
    combined = (base_text or "").strip()
    if not should_supplement_with_ocr(combined, file_size_bytes):
        return OcrSupplementResult(
            text=combined,
            applied=False,
            source="none",
            attempted=False,
        )

    if not is_ocr_available():
        return OcrSupplementResult(
            text=combined,
            applied=False,
            source="none",
            attempted=True,
        )

    def _run() -> tuple[str, str, int, int]:
        if doc_kind == "pdf":
            ocr_body, processed, total = _ocr_pdf_sync(file_path)
            return ocr_body, "pdf_pages", processed, total
        if doc_kind == "docx":
            ocr_body, processed, total = _ocr_docx_sync(file_path)
            return ocr_body, "docx_images", processed, total
        return "", "none", 0, 0

    try:
        ocr_body, source, processed, total = await asyncio.to_thread(_run)
    except Exception as exc:
        logger.exception("文档 OCR 补充失败: %s", exc)
        return OcrSupplementResult(
            text=combined, applied=False, source="none", attempted=True
        )

    ocr_body = (ocr_body or "").strip()
    if not ocr_body:
        return OcrSupplementResult(
            text=combined,
            applied=False,
            source=source,
            attempted=True,
            units_processed=processed,
            units_total=total,
        )

    merged = combined
    if merged:
        merged += "\n\n"
    merged += "--- OCR 识别内容（供检索） ---\n" + ocr_body

    return OcrSupplementResult(
        text=merged,
        applied=True,
        source=source,
        attempted=True,
        units_processed=processed,
        units_total=total,
        ocr_char_count=len(ocr_body),
    )


def format_ocr_upload_hint(result: OcrSupplementResult) -> str:
    """生成上传成功消息中的 OCR 说明。"""
    hints: list[str] = []
    if result.embedded_images_saved > 0:
        hints.append(f"已导出内嵌图片 {result.embedded_images_saved} 张")
    if not result.attempted and not hints:
        return ""
    if not result.applied:
        if result.attempted and not is_ocr_available() and result.embedded_images_saved == 0:
            hints.append("疑似扫描件；未安装 rapidocr 未补充 OCR")
        elif result.attempted and result.units_processed > 0 and result.ocr_char_count <= 0:
            if not hints:
                hints.append("已尝试 OCR，图中未识别到有效文字")
    else:
        unit_label = "页" if result.source == "pdf_pages" else "张图"
        extra = ""
        if result.units_total > result.units_processed > 0:
            extra = f"（共 {result.units_total} {unit_label}，处理 {result.units_processed}）"
        hints.append(f"OCR 约 {result.ocr_char_count} 字{extra}")

    return f"（{'；'.join(hints)}）" if hints else ""
