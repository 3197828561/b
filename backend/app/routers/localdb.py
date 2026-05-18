"""公司本地数据库相关接口（文件上传/抽取/列表/下载/删除）。"""

import os
import re
import uuid
import mimetypes
from datetime import datetime
from typing import Optional

import aiofiles
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..config import settings
from ..models.schemas import (
    LocalDbFileActionResponse,
    LocalDbFileInfo,
    LocalDbFileListResponse,
    LocalDbFileUploadResponse,
    LocalDbRebuildFileResult,
    LocalDbRebuildResponse,
    LocalDbTemplateInfoResponse,
)
from ..services.file_service import FileService
from ..services.localdb_knowledge_service import LocalDbKnowledgeService, now_mtime_str
from ..services.localdb_rebuild_service import rebuild_company_knowledge
from ..services.ocr_service import (
    OcrSupplementResult,
    _merge_ocr_results,
    format_ocr_upload_hint,
    supplement_document_text,
    supplement_embedded_docx_images,
)
from ..utils.localdb_paths import (
    LOCALDB_ALL_FILE_DIRS,
    LOCALDB_FILES_DIR,
    LOCALDB_KNOWLEDGE_FILE_KIND,
    LOCALDB_TEMPLATE_DIR,
    LOCALDB_TEMPLATE_FILENAME,
    localdb_extracted_images_dir,
    localdb_target_dir,
    localdb_template_exists,
    localdb_template_path,
    sanitize_company_id,
)

router = APIRouter(prefix="/api/localdb", tags=["公司本地数据库"])


class LocalDbCompanyInfoRequest(BaseModel):
    company_name: str
    unified_code: str
    established_date: str
    legal_representative: str
    registered_capital: str
    address: str
    enterprise_scale: str
    business_nature: str


def _company_id_or_raise(company_id: str) -> str:
    try:
        return sanitize_company_id(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def unique_localdb_filename(target_dir: str, original_name: str) -> str:
    """保留原始文件名；重名时在扩展名前追加 _1、_2…"""
    base = safe_localdb_filename(original_name or "unknown_file")
    name_part, ext = os.path.splitext(base)
    name_part = re.sub(r'[<>:"/\\|?*\x00]', "_", name_part).strip().strip(".")
    if not name_part:
        name_part = "file"
    ext = ext.lower()
    candidate = f"{name_part}{ext}"
    full = os.path.join(target_dir, candidate)
    if not os.path.exists(full):
        return candidate
    for i in range(1, 1000):
        candidate = f"{name_part}_{i}{ext}"
        if not os.path.exists(os.path.join(target_dir, candidate)):
            return candidate
    return f"{name_part}_{uuid.uuid4().hex[:8]}{ext}"


async def save_localdb_file(upload_file: UploadFile, target_dir: str) -> str:
    os.makedirs(target_dir, exist_ok=True)

    content = await upload_file.read()
    original_name = upload_file.filename or "unknown_file"

    if len(content) > settings.max_file_size:
        limit_mb = int(settings.max_file_size / 1024 / 1024)
        raise ValueError(f"文件大小超过限制（最大 {limit_mb}MB）")

    new_name = unique_localdb_filename(target_dir, original_name)
    file_path = os.path.join(target_dir, new_name)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    return file_path


async def save_localdb_file_from_bytes(content: bytes, original_name: str, target_dir: str) -> str:
    os.makedirs(target_dir, exist_ok=True)

    if len(content) > settings.max_file_size:
        limit_mb = int(settings.max_file_size / 1024 / 1024)
        raise ValueError(f"文件大小超过限制（最大 {limit_mb}MB）")

    new_name = unique_localdb_filename(target_dir, original_name)
    file_path = os.path.join(target_dir, new_name)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    return file_path


async def extract_text_from_upload_bytes(
    content: bytes,
    content_type: Optional[str],
    filename: Optional[str],
    company_id: str = "default",
) -> tuple[str, OcrSupplementResult]:
    """
    从上传字节中抽取 PDF/Word 文本，并兼容 .doc(需要转换)。
    扫描件在正文过少时会自动 OCR 补充，供本地库 RAG 检索。
    """
    if not FileService.is_supported_document(content_type, filename):
        raise ValueError(FileService.SUPPORTED_DOCUMENTS_MESSAGE)

    tmp_dir = os.path.join(settings.upload_dir, "localdb", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    safe_name = os.path.basename(filename or "unknown_file")
    _, ext = os.path.splitext(safe_name)
    doc_kind = FileService._get_document_kind(content_type, filename)
    ext = ext.lower() or (
        ".pdf" if doc_kind == "pdf" else ".txt" if doc_kind == "text" else ".docx"
    )
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{ext}")

    async with aiofiles.open(tmp_path, "wb") as f:
        await f.write(content)

    cleanup_paths: list[str] = []
    try:
        base_text, ocr_kind, cleanup_paths = (
            await FileService.extract_localdb_document_text_from_path(
                tmp_path, content_type=content_type, filename=filename
            )
        )
        if ocr_kind == "text":
            ocr_result = OcrSupplementResult(
                text=(base_text or "").strip(), applied=False, source="none"
            )
            return ocr_result.text, ocr_result
        ocr_path = tmp_path if ocr_kind == "pdf" else FileService._pick_ocr_docx_path(
            tmp_path, cleanup_paths
        )
        ocr_result = await supplement_document_text(
            ocr_path, ocr_kind, base_text, len(content)
        )
        if ocr_kind == "docx":
            embed_result = await supplement_embedded_docx_images(
                ocr_path,
                company_id,
                safe_name,
                ocr_result.text,
            )
            ocr_result = _merge_ocr_results(ocr_result, embed_result)
        return ocr_result.text, ocr_result
    finally:
        FileService._cleanup_temp_paths(cleanup_paths)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def safe_localdb_filename(name: str) -> str:
    return os.path.basename(name)


def guess_mime_type(filename: str) -> str:
    mtype, _ = mimetypes.guess_type(filename)
    return mtype or "application/octet-stream"


def list_localdb_files(company_id: str, doc_kind: str) -> list[LocalDbFileInfo]:
    target_dir = localdb_target_dir(company_id, doc_kind)
    os.makedirs(target_dir, exist_ok=True)

    files: list[LocalDbFileInfo] = []
    for fn in os.listdir(target_dir):
        full_path = os.path.join(target_dir, fn)
        if not os.path.isfile(full_path):
            continue
        stat = os.stat(full_path)
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        files.append(
            LocalDbFileInfo(name=fn, size_bytes=int(stat.st_size), mtime=mtime)
        )

    files.sort(key=lambda x: x.mtime, reverse=True)
    return files


def get_localdb_file_path(company_id: str, doc_kind: str, name: str) -> str:
    target_dir = localdb_target_dir(company_id, doc_kind)
    safe_name = safe_localdb_filename(name)
    full_path = os.path.join(target_dir, safe_name)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return full_path


def list_merged_localdb_files(company_id: str) -> list[LocalDbFileInfo]:
    """合并 files 与历史 tender/bid 目录中的文件列表（按时间倒序）。"""
    seen: set[str] = set()
    merged: list[LocalDbFileInfo] = []
    for doc_kind in LOCALDB_ALL_FILE_DIRS:
        for info in list_localdb_files(company_id, doc_kind):
            if info.name in seen:
                continue
            seen.add(info.name)
            merged.append(info)
    merged.sort(key=lambda x: x.mtime, reverse=True)
    return merged


def resolve_localdb_file_path(company_id: str, name: str) -> str:
    safe_name = safe_localdb_filename(name)
    for doc_kind in LOCALDB_ALL_FILE_DIRS:
        full_path = os.path.join(localdb_target_dir(company_id, doc_kind), safe_name)
        if os.path.isfile(full_path):
            return full_path
    raise HTTPException(status_code=404, detail="文件不存在")


def _delete_localdb_file_knowledge(knowledge: LocalDbKnowledgeService, filename: str) -> None:
    """删除知识库切片（兼容历史 tender/bid 与统一 file）。"""
    for kind in (LOCALDB_KNOWLEDGE_FILE_KIND, "tender", "bid"):
        knowledge.delete_upload_chunks(source_kind=kind, source_file=filename)


async def upload_localdb_document_file(
    cid: str, file: UploadFile
) -> LocalDbFileUploadResponse:
    if not FileService.is_supported_document(file.content_type, file.filename):
        return LocalDbFileUploadResponse(
            success=False, message=FileService.SUPPORTED_DOCUMENTS_MESSAGE
        )

    content = await file.read()
    original_name = file.filename or "unknown_file"
    file_path = await save_localdb_file_from_bytes(
        content, original_name, localdb_target_dir(cid, LOCALDB_FILES_DIR)
    )

    extracted_text, ocr_result = await extract_text_from_upload_bytes(
        content=content,
        content_type=file.content_type,
        filename=file.filename,
        company_id=cid,
    )
    stored_name = os.path.basename(file_path)
    knowledge = LocalDbKnowledgeService(cid)
    for legacy_kind in ("tender", "bid"):
        knowledge.delete_upload_chunks(source_kind=legacy_kind, source_file=stored_name)
    knowledge.upsert_chunks_for_kind(
        source_kind=LOCALDB_KNOWLEDGE_FILE_KIND,
        source_file=stored_name,
        extracted_text=extracted_text,
        mtime=now_mtime_str(),
    )
    ocr_hint = format_ocr_upload_hint(ocr_result)
    return LocalDbFileUploadResponse(
        success=True,
        message=f"文件已提交：{file.filename}{ocr_hint}",
        file_path=file_path,
        ocr_applied=ocr_result.applied,
        ocr_char_count=ocr_result.ocr_char_count,
    )


@router.post("/files/upload", response_model=LocalDbFileUploadResponse)
async def upload_files(
    file: UploadFile = File(...),
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    cid = _company_id_or_raise(company_id)
    try:
        return await upload_localdb_document_file(cid, file)
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.get("/files/list", response_model=LocalDbFileListResponse)
async def list_files(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    try:
        files = list_merged_localdb_files(cid)
        return LocalDbFileListResponse(success=True, message="ok", files=files)
    except Exception as exc:
        return LocalDbFileListResponse(success=False, message=str(exc), files=[])


@router.delete("/files/delete", response_model=LocalDbFileActionResponse)
async def delete_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    try:
        path = resolve_localdb_file_path(cid, name)
        os.remove(path)
        FileService.remove_localdb_extracted_images(cid, safe_localdb_filename(name))
        knowledge = LocalDbKnowledgeService(cid)
        _delete_localdb_file_knowledge(knowledge, safe_localdb_filename(name))
        return LocalDbFileActionResponse(success=True, message="删除成功")
    except HTTPException as exc:
        return LocalDbFileActionResponse(success=False, message=str(exc.detail))
    except Exception as exc:
        return LocalDbFileActionResponse(success=False, message=str(exc))


@router.get("/files/download")
async def download_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    path = resolve_localdb_file_path(cid, name)
    safe_name = safe_localdb_filename(name)
    return FileResponse(path, filename=safe_name, media_type=guess_mime_type(safe_name))


@router.get("/files/extracted-image")
async def download_extracted_image(
    source: str = Query(..., description="资料文件名（与上传时一致）"),
    image: str = Query(..., description="图片文件名，如 img_1.png"),
    company_id: str = Query("default"),
):
    """下载某资料文件导出到本地库的内嵌图片。"""
    cid = _company_id_or_raise(company_id)
    safe_source = safe_localdb_filename(source)
    safe_image = os.path.basename(image)
    if not re.fullmatch(r"img_\d+\.(png|jpg|jpeg|gif|bmp|webp)", safe_image, re.I):
        raise HTTPException(status_code=400, detail="无效的图片文件名")
    img_path = os.path.join(
        localdb_extracted_images_dir(cid, safe_source), safe_image
    )
    if not os.path.isfile(img_path):
        raise HTTPException(status_code=404, detail="图片不存在，请重新上传该资料")
    return FileResponse(img_path, filename=safe_image, media_type=guess_mime_type(safe_image))


# 兼容旧接口：行为与 /files/* 一致
@router.post("/tender/upload", response_model=LocalDbFileUploadResponse)
async def upload_tender_file(
    file: UploadFile = File(...),
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    cid = _company_id_or_raise(company_id)
    try:
        return await upload_localdb_document_file(cid, file)
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.post("/bid/upload", response_model=LocalDbFileUploadResponse)
async def upload_bid_file(
    file: UploadFile = File(...),
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    cid = _company_id_or_raise(company_id)
    try:
        return await upload_localdb_document_file(cid, file)
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.get("/tender/list", response_model=LocalDbFileListResponse)
async def list_tender_files(company_id: str = Query("default")):
    return await list_files(company_id)


@router.get("/bid/list", response_model=LocalDbFileListResponse)
async def list_bid_files(company_id: str = Query("default")):
    return await list_files(company_id)


@router.delete("/tender/delete", response_model=LocalDbFileActionResponse)
async def delete_tender_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    return await delete_file(name=name, company_id=company_id)


@router.delete("/bid/delete", response_model=LocalDbFileActionResponse)
async def delete_bid_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    return await delete_file(name=name, company_id=company_id)


@router.get("/tender/download")
async def download_tender_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    return await download_file(name=name, company_id=company_id)


@router.get("/bid/download")
async def download_bid_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    return await download_file(name=name, company_id=company_id)


def _template_info_response(cid: str) -> LocalDbTemplateInfoResponse:
    path = localdb_template_path(cid)
    if not os.path.isfile(path):
        return LocalDbTemplateInfoResponse(
            success=True,
            message="未上传模板，导出将使用系统默认版式",
            exists=False,
        )
    stat = os.stat(path)
    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return LocalDbTemplateInfoResponse(
        success=True,
        message="已配置导出模板",
        exists=True,
        filename=LOCALDB_TEMPLATE_FILENAME,
        size_bytes=int(stat.st_size),
        mtime=mtime,
    )


@router.get("/template/info", response_model=LocalDbTemplateInfoResponse)
async def get_template_info(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    try:
        return _template_info_response(cid)
    except Exception as exc:
        return LocalDbTemplateInfoResponse(success=False, message=str(exc), exists=False)


@router.post("/template/upload", response_model=LocalDbFileUploadResponse)
async def upload_export_template(
    file: UploadFile = File(...),
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    """上传该公司投标 Word 导出模板（.docx），导出时保留封面/页眉页脚/样式，正文接在模板后。"""
    cid = _company_id_or_raise(company_id)
    try:
        filename = file.filename or ""
        if not filename.lower().endswith(".docx"):
            return LocalDbFileUploadResponse(
                success=False,
                message="请上传 .docx 格式的 Word 模板",
            )

        content = await file.read()
        if len(content) < 4 or not content.startswith(b"PK"):
            return LocalDbFileUploadResponse(
                success=False, message="文件不是有效的 docx（请用 Word 另存为 .docx）"
            )

        target_dir = localdb_target_dir(cid, LOCALDB_TEMPLATE_DIR)
        os.makedirs(target_dir, exist_ok=True)
        dest = localdb_template_path(cid)
        async with aiofiles.open(dest, "wb") as f:
            await f.write(content)

        display = safe_localdb_filename(filename)
        return LocalDbFileUploadResponse(
            success=True,
            message=f"导出模板已保存：{display}（导出 Word 时将套用该公司模板）",
            file_path=dest,
        )
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.delete("/template/delete", response_model=LocalDbFileActionResponse)
async def delete_export_template(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    try:
        path = localdb_template_path(cid)
        if os.path.isfile(path):
            os.remove(path)
        return LocalDbFileActionResponse(success=True, message="已删除导出模板")
    except Exception as exc:
        return LocalDbFileActionResponse(success=False, message=str(exc))


@router.get("/template/download")
async def download_export_template(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    path = localdb_template_path(cid)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="尚未上传导出模板")
    return FileResponse(
        path,
        filename="投标导出模板.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/appendix/list", response_model=LocalDbFileListResponse)
async def list_appendix_templates(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    try:
        from ..services.appendix_service import list_appendix_templates as _list

        files = _list(cid)
        return LocalDbFileListResponse(success=True, message="ok", files=files)
    except Exception as exc:
        return LocalDbFileListResponse(success=False, message=str(exc), files=[])


@router.post("/appendix/upload", response_model=LocalDbFileUploadResponse)
async def upload_appendix_template(
    file: UploadFile = File(...),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    try:
        from ..services.appendix_service import appendix_root, ensure_default_templates

        ensure_default_templates(cid)
        filename = safe_localdb_filename(file.filename or "附录.docx")
        if not filename.lower().endswith(".docx"):
            return LocalDbFileUploadResponse(
                success=False, message="请上传 .docx 附录模板"
            )
        content = await file.read()
        dest = os.path.join(appendix_root(cid), filename)
        async with aiofiles.open(dest, "wb") as f:
            await f.write(content)
        return LocalDbFileUploadResponse(
            success=True,
            message=f"附录模板已保存：{filename}（支持占位符如 {{company_name}}）",
            file_path=dest,
        )
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.get("/appendix/download")
async def download_appendix_template(
    name: str = Query(...),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    from ..services.appendix_service import appendix_root

    path = os.path.join(appendix_root(cid), safe_localdb_filename(name))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="模板不存在")
    return FileResponse(path, filename=safe_localdb_filename(name), media_type=guess_mime_type(name))


@router.get("/appendix/download-filled-zip")
async def download_filled_appendix_zip(
    company_id: str = Query("default"),
    project_name: str = Query("", description="项目名称，填入 {{project_name}}"),
):
    cid = _company_id_or_raise(company_id)
    try:
        from ..services.appendix_service import build_filled_appendix_zip

        buf = build_filled_appendix_zip(cid, project_name=project_name or None)
        filename = "投标附录.zip"
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/knowledge/rebuild", response_model=LocalDbRebuildResponse)
async def rebuild_knowledge_index(
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    """
    从磁盘已上传资料文件重新抽取文本（含 OCR）并写入 knowledge.json。
    公司基本信息切片保留；资料类切片会先清空再重建。
    """
    cid = _company_id_or_raise(company_id)
    try:
        result = await rebuild_company_knowledge(cid)
        return LocalDbRebuildResponse(
            success=result.success,
            message=result.message,
            processed=result.processed,
            failed=result.failed,
            skipped=result.skipped,
            ocr_files=result.ocr_files,
            total_chars=result.total_chars,
            cleared_chunks=result.cleared_chunks,
            file_results=[
                LocalDbRebuildFileResult(
                    name=fr.name,
                    source_kind=fr.source_kind,
                    success=fr.success,
                    char_count=fr.char_count,
                    ocr_applied=fr.ocr_applied,
                    error=fr.error,
                )
                for fr in result.file_results
            ],
        )
    except Exception as exc:
        return LocalDbRebuildResponse(success=False, message=str(exc))


@router.post("/company/upload", response_model=LocalDbFileUploadResponse)
async def upload_company_info_file(
    file: UploadFile = File(...),
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    """上传公司基本信息文档（Word/PDF），抽取文本并写入知识库。"""
    cid = _company_id_or_raise(company_id)
    try:
        if not FileService.is_supported_document(file.content_type, file.filename):
            return LocalDbFileUploadResponse(
                success=False, message=FileService.SUPPORTED_DOCUMENTS_MESSAGE
            )

        content = await file.read()
        original_name = file.filename or "unknown_file"
        file_path = await save_localdb_file_from_bytes(
            content, original_name, localdb_target_dir(cid, "company")
        )

        extracted_text, ocr_result = await extract_text_from_upload_bytes(
            content=content,
            content_type=file.content_type,
            filename=file.filename,
            company_id=cid,
        )
        knowledge = LocalDbKnowledgeService(cid)
        knowledge.upsert_chunks_for_kind(
            source_kind="company",
            source_file=os.path.basename(file_path),
            extracted_text=extracted_text,
            mtime=now_mtime_str(),
        )
        ocr_hint = format_ocr_upload_hint(ocr_result)
        return LocalDbFileUploadResponse(
            success=True,
            message=f"公司基本信息已提交：{file.filename}{ocr_hint}",
            file_path=file_path,
            ocr_applied=ocr_result.applied,
            ocr_char_count=ocr_result.ocr_char_count,
        )
    except Exception as exc:
        return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.get("/company/list", response_model=LocalDbFileListResponse)
async def list_company_info_files(company_id: str = Query("default")):
    cid = _company_id_or_raise(company_id)
    try:
        files = list_localdb_files(cid, "company")
        return LocalDbFileListResponse(success=True, message="ok", files=files)
    except Exception as exc:
        return LocalDbFileListResponse(success=False, message=str(exc), files=[])


@router.delete("/company/delete", response_model=LocalDbFileActionResponse)
async def delete_company_info_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    try:
        path = get_localdb_file_path(cid, "company", name)
        os.remove(path)
        knowledge = LocalDbKnowledgeService(cid)
        knowledge.delete_upload_chunks(source_kind="company", source_file=name)
        return LocalDbFileActionResponse(success=True, message="删除成功")
    except HTTPException as exc:
        return LocalDbFileActionResponse(success=False, message=str(exc.detail))
    except Exception as exc:
        return LocalDbFileActionResponse(success=False, message=str(exc))


@router.get("/company/download")
async def download_company_info_file(
    name: str = Query(..., description="文件名"),
    company_id: str = Query("default"),
):
    cid = _company_id_or_raise(company_id)
    path = get_localdb_file_path(cid, "company", name)
    return FileResponse(path, filename=safe_localdb_filename(name), media_type=guess_mime_type(name))


@router.post("/company/save")
async def save_company_info(
    request: LocalDbCompanyInfoRequest,
    company_id: str = Query("default", description="本地库归属公司 ID"),
):
    cid = _company_id_or_raise(company_id)
    try:
        company_text = "\n".join(
            [
                f"公司名称：{request.company_name}",
                f"统一社会信用代码：{request.unified_code}",
                f"成立时间：{request.established_date}",
                f"法定代表人：{request.legal_representative}",
                f"注册资本：{request.registered_capital}",
                f"注册/经营地址：{request.address}",
                f"企业规模：{request.enterprise_scale}",
                f"经营性质：{request.business_nature}",
            ]
        )
        knowledge = LocalDbKnowledgeService(cid)
        knowledge.upsert_company_chunks(company_text=company_text, mtime=now_mtime_str())
        from ..services.appendix_service import save_company_profile

        save_company_profile(
            cid,
            {
                "company_name": request.company_name,
                "unified_code": request.unified_code,
                "established_date": request.established_date,
                "legal_representative": request.legal_representative,
                "registered_capital": request.registered_capital,
                "address": request.address,
                "enterprise_scale": request.enterprise_scale,
                "business_nature": request.business_nature,
            },
        )
        return {"success": True, "message": "公司基本信息已保存", "mtime": now_mtime_str()}
    except Exception as exc:
        return {"success": False, "message": str(exc)}
