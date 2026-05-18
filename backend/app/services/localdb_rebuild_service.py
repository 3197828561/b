"""从磁盘已上传文件重建本地库知识索引（含 OCR 补充）。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import aiofiles

from .file_service import FileService
from .localdb_knowledge_service import LocalDbKnowledgeService, now_mtime_str
from .ocr_service import (
    OcrSupplementResult,
    _merge_ocr_results,
    supplement_document_text,
    supplement_embedded_docx_images,
)
from ..config import settings
from ..utils.localdb_paths import (
    LOCALDB_ALL_FILE_DIRS,
    LOCALDB_KNOWLEDGE_FILE_KIND,
    localdb_target_dir,
)

logger = logging.getLogger(__name__)

KNOWLEDGE_FILE_KINDS_TO_CLEAR = (LOCALDB_KNOWLEDGE_FILE_KIND, "tender", "bid")


@dataclass
class RebuildFileResult:
    name: str
    source_kind: str
    success: bool
    char_count: int = 0
    ocr_applied: bool = False
    error: Optional[str] = None


@dataclass
class RebuildKnowledgeResult:
    success: bool
    message: str
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    ocr_files: int = 0
    total_chars: int = 0
    cleared_chunks: int = 0
    file_results: list[RebuildFileResult] = field(default_factory=list)


async def _extract_text_from_disk_path(
    file_path: str, company_id: str
) -> tuple[str, OcrSupplementResult]:
    """读取磁盘文件并抽取文本（含按需 OCR）。"""
    filename = os.path.basename(file_path)
    doc_kind = FileService._get_document_kind(None, filename)
    if not doc_kind:
        raise ValueError(f"{filename}：{FileService.SUPPORTED_DOCUMENTS_MESSAGE}")

    async with aiofiles.open(file_path, "rb") as f:
        content = await f.read()

    cleanup_paths: list[str] = []
    try:
        base_text, ocr_kind, cleanup_paths = (
            await FileService.extract_localdb_document_text_from_path(
                file_path, filename=filename
            )
        )
        if ocr_kind == "text":
            ocr_result = OcrSupplementResult(
                text=(base_text or "").strip(), applied=False, source="none"
            )
            return ocr_result.text, ocr_result
        ocr_path = (
            file_path
            if ocr_kind == "pdf"
            else FileService._pick_ocr_docx_path(file_path, cleanup_paths)
        )
        ocr_result = await supplement_document_text(
            ocr_path, ocr_kind, base_text, len(content)
        )
        if ocr_kind == "docx":
            embed_result = await supplement_embedded_docx_images(
                ocr_path, company_id, filename, ocr_result.text
            )
            ocr_result = _merge_ocr_results(ocr_result, embed_result)
        return ocr_result.text, ocr_result
    finally:
        FileService._cleanup_temp_paths(cleanup_paths)


def _list_all_disk_files(company_id: str) -> list[tuple[str, str]]:
    """返回 (目录名, 文件名) 列表，跨 files/tender/bid 去重。"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for doc_kind in LOCALDB_ALL_FILE_DIRS:
        target_dir = localdb_target_dir(company_id, doc_kind)
        if not os.path.isdir(target_dir):
            continue
        for fn in sorted(os.listdir(target_dir)):
            full = os.path.join(target_dir, fn)
            if not os.path.isfile(full) or fn in seen:
                continue
            seen.add(fn)
            out.append((doc_kind, fn))
    out.sort(key=lambda x: x[1])
    return out


async def rebuild_company_knowledge(company_id: str) -> RebuildKnowledgeResult:
    """
    按磁盘资料文件重建 knowledge.json 中的 file/tender/bid 切片。
    公司基本信息（company）切片保留不变。
    """
    knowledge = LocalDbKnowledgeService(company_id)
    cleared = knowledge.clear_document_chunks(list(KNOWLEDGE_FILE_KINDS_TO_CLEAR))

    tasks = _list_all_disk_files(company_id)
    if not tasks:
        return RebuildKnowledgeResult(
            success=True,
            message="没有需要重建的磁盘文件",
            cleared_chunks=cleared,
        )

    processed = 0
    failed = 0
    skipped = 0
    ocr_files = 0
    total_chars = 0
    file_results: list[RebuildFileResult] = []

    for doc_kind, filename in tasks:
        file_path = os.path.join(localdb_target_dir(company_id, doc_kind), filename)
        stat = os.stat(file_path)
        if stat.st_size == 0:
            skipped += 1
            file_results.append(
                RebuildFileResult(
                    name=filename,
                    source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
                    success=False,
                    error="空文件，已跳过",
                )
            )
            continue

        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        try:
            extracted_text, ocr_result = await _extract_text_from_disk_path(
                file_path, company_id
            )
            text = (extracted_text or "").strip()
            if not text:
                skipped += 1
                file_results.append(
                    RebuildFileResult(
                        name=filename,
                        source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
                        success=False,
                        error="未抽取到有效文本",
                    )
                )
                continue

            for legacy_kind in KNOWLEDGE_FILE_KINDS_TO_CLEAR:
                knowledge.delete_upload_chunks(
                    source_kind=legacy_kind, source_file=filename
                )
            knowledge.upsert_chunks_for_kind(
                source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
                source_file=filename,
                extracted_text=text,
                mtime=mtime or now_mtime_str(),
            )
            processed += 1
            total_chars += len(text)
            if ocr_result.applied:
                ocr_files += 1
            file_results.append(
                RebuildFileResult(
                    name=filename,
                    source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
                    success=True,
                    char_count=len(text),
                    ocr_applied=ocr_result.applied,
                )
            )
        except Exception as exc:
            failed += 1
            logger.exception("重建知识库失败 %s", filename)
            file_results.append(
                RebuildFileResult(
                    name=filename,
                    source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
                    success=False,
                    error=str(exc),
                )
            )

    if failed == 0 and processed > 0:
        msg = (
            f"资料知识库已重建：成功 {processed} 个"
            f"（其中 OCR {ocr_files} 个），共约 {total_chars} 字"
        )
        if skipped:
            msg += f"，跳过 {skipped} 个"
        success = True
    elif processed > 0:
        msg = f"部分完成：成功 {processed}，失败 {failed}，跳过 {skipped}"
        success = failed < len(tasks)
    else:
        msg = f"重建失败：无成功文件（失败 {failed}，跳过 {skipped}）"
        success = False

    if processed > 0 and settings.embedding_enabled:
        try:
            from .embedding_service import sync_embeddings_for_chunks

            all_chunks = knowledge.load_index().get("chunks") or []
            await sync_embeddings_for_chunks(company_id, all_chunks)
        except Exception as exc:
            logger.warning("重建后向量索引同步失败: %s", exc)

    return RebuildKnowledgeResult(
        success=success,
        message=msg,
        processed=processed,
        failed=failed,
        skipped=skipped,
        ocr_files=ocr_files,
        total_chars=total_chars,
        cleared_chunks=cleared,
        file_results=file_results,
    )
