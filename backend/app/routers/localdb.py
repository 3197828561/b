"""公司本地数据库相关接口（文件上传/抽取/列表/下载/删除）。"""

import os
import uuid
import mimetypes
from datetime import datetime
from typing import Optional

import aiofiles
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..models.schemas import (
  LocalDbFileActionResponse,
  LocalDbFileInfo,
  LocalDbFileListResponse,
  LocalDbFileUploadResponse,
)
from ..services.file_service import FileService
from ..services.localdb_knowledge_service import LocalDbKnowledgeService, now_mtime_str

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


async def save_localdb_file(upload_file: UploadFile, target_dir: str) -> str:
  os.makedirs(target_dir, exist_ok=True)

  content = await upload_file.read()
  original_name = upload_file.filename or "unknown_file"
  _, ext = os.path.splitext(original_name)
  ext = ext.lower()

  if len(content) > settings.max_file_size:
    limit_mb = int(settings.max_file_size / 1024 / 1024)
    raise ValueError(f"文件大小超过限制（最大 {limit_mb}MB）")

  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
  new_name = f"{timestamp}_{uuid.uuid4().hex}{ext}"
  file_path = os.path.join(target_dir, new_name)

  async with aiofiles.open(file_path, "wb") as f:
    await f.write(content)

  return file_path


async def save_localdb_file_from_bytes(content: bytes, original_name: str, target_dir: str) -> str:
  os.makedirs(target_dir, exist_ok=True)

  _, ext = os.path.splitext(original_name)
  ext = ext.lower()
  if len(content) > settings.max_file_size:
    limit_mb = int(settings.max_file_size / 1024 / 1024)
    raise ValueError(f"文件大小超过限制（最大 {limit_mb}MB）")

  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
  new_name = f"{timestamp}_{uuid.uuid4().hex}{ext}"
  file_path = os.path.join(target_dir, new_name)
  async with aiofiles.open(file_path, "wb") as f:
    await f.write(content)
  return file_path


async def extract_text_from_upload_bytes(
  content: bytes, content_type: Optional[str], filename: Optional[str]
) -> str:
  """
  从上传字节中抽取 PDF/Word 文本，并兼容 .doc(需要转换)。
  为了复用现有抽取能力，这里会把内容落到临时文件，再调用 FileService 的抽取方法。
  """
  file_header = content[:8]
  doc_kind = FileService._get_document_kind(content_type, filename)  # pdf / docx
  if not doc_kind:
    raise ValueError("不支持的文件类型，请上传PDF或Word文档")

  tmp_dir = os.path.join(settings.upload_dir, "localdb", "tmp")
  os.makedirs(tmp_dir, exist_ok=True)

  # 临时扩展名尽量保持原样，避免解析依赖扩展名
  safe_name = os.path.basename(filename or "unknown_file")
  _, ext = os.path.splitext(safe_name)
  ext = ext.lower() or (".pdf" if doc_kind == "pdf" else ".docx")
  tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}{ext}")

  async with aiofiles.open(tmp_path, "wb") as f:
    await f.write(content)

  try:
    if doc_kind == "pdf":
      return await FileService.extract_text_from_pdf(tmp_path)

    # docx（可能是 .doc 或 .docx 误判/兜底）
    if doc_kind == "docx":
      is_zip_docx = file_header.startswith(b"PK")
      if not is_zip_docx:
        is_legacy_doc = file_header.startswith(
          b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
        )
        if is_legacy_doc:
          converted_docx_path = FileService._convert_doc_to_docx_windows(tmp_path)
          text = await FileService.extract_text_from_docx(converted_docx_path)
          FileService._safe_file_cleanup(converted_docx_path)
          return text
        raise ValueError("当前 Word 文件不是 docx 格式。请将文档另存为 .docx 后再上传。")

      return await FileService.extract_text_from_docx(tmp_path)

    raise ValueError("不支持的文件类型，请上传PDF或Word文档")
  finally:
    # 释放临时文件
    try:
      if os.path.exists(tmp_path):
        os.remove(tmp_path)
    except Exception:
      pass


def localdb_target_dir(doc_kind: str) -> str:
  # 统一落盘到后端 upload_dir 下的 localdb 子目录
  return os.path.join(settings.upload_dir, "localdb", doc_kind)


def safe_localdb_filename(name: str) -> str:
  # 防止路径穿越；只保留文件名部分
  return os.path.basename(name)


def guess_mime_type(filename: str) -> str:
  mtype, _ = mimetypes.guess_type(filename)
  return mtype or "application/octet-stream"


def list_localdb_files(doc_kind: str) -> list[LocalDbFileInfo]:
  target_dir = localdb_target_dir(doc_kind)
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

  # 按修改时间倒序显示
  files.sort(key=lambda x: x.mtime, reverse=True)
  return files


def get_localdb_file_path(doc_kind: str, name: str) -> str:
  target_dir = localdb_target_dir(doc_kind)
  safe_name = safe_localdb_filename(name)
  full_path = os.path.join(target_dir, safe_name)
  if not os.path.isfile(full_path):
    raise HTTPException(status_code=404, detail="文件不存在")
  return full_path


@router.post("/tender/upload", response_model=LocalDbFileUploadResponse)
async def upload_tender_file(file: UploadFile = File(...)):
  try:
    if not FileService.is_supported_document(file.content_type, file.filename):
      return LocalDbFileUploadResponse(
        success=False, message="不支持的文件类型，请上传PDF或Word文档"
      )

    content = await file.read()
    original_name = file.filename or "unknown_file"
    file_path = await save_localdb_file_from_bytes(content, original_name, localdb_target_dir("tender"))

    # 抽取文本并写入知识库
    extracted_text = await extract_text_from_upload_bytes(
      content=content,
      content_type=file.content_type,
      filename=file.filename,
    )
    knowledge = LocalDbKnowledgeService()
    knowledge.upsert_upload_chunks(
      source_kind="tender",
      source_file=os.path.basename(file_path),
      extracted_text=extracted_text,
      mtime=now_mtime_str(),
    )
    return LocalDbFileUploadResponse(
      success=True, message=f"招标文件已提交：{file.filename}", file_path=file_path
    )
  except Exception as exc:
    return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.post("/bid/upload", response_model=LocalDbFileUploadResponse)
async def upload_bid_file(file: UploadFile = File(...)):
  try:
    if not FileService.is_supported_document(file.content_type, file.filename):
      return LocalDbFileUploadResponse(
        success=False, message="不支持的文件类型，请上传PDF或Word文档"
      )

    content = await file.read()
    original_name = file.filename or "unknown_file"
    file_path = await save_localdb_file_from_bytes(content, original_name, localdb_target_dir("bid"))

    extracted_text = await extract_text_from_upload_bytes(
      content=content,
      content_type=file.content_type,
      filename=file.filename,
    )
    knowledge = LocalDbKnowledgeService()
    knowledge.upsert_upload_chunks(
      source_kind="bid",
      source_file=os.path.basename(file_path),
      extracted_text=extracted_text,
      mtime=now_mtime_str(),
    )
    return LocalDbFileUploadResponse(
      success=True, message=f"投标文件已提交：{file.filename}", file_path=file_path
    )
  except Exception as exc:
    return LocalDbFileUploadResponse(success=False, message=str(exc))


@router.get("/tender/list", response_model=LocalDbFileListResponse)
async def list_tender_files():
  try:
    files = list_localdb_files("tender")
    return LocalDbFileListResponse(success=True, message="ok", files=files)
  except Exception as exc:
    return LocalDbFileListResponse(success=False, message=str(exc), files=[])


@router.get("/bid/list", response_model=LocalDbFileListResponse)
async def list_bid_files():
  try:
    files = list_localdb_files("bid")
    return LocalDbFileListResponse(success=True, message="ok", files=files)
  except Exception as exc:
    return LocalDbFileListResponse(success=False, message=str(exc), files=[])


@router.delete("/tender/delete", response_model=LocalDbFileActionResponse)
async def delete_tender_file(name: str = Query(..., description="文件名")):
  try:
    path = get_localdb_file_path("tender", name)
    os.remove(path)
    knowledge = LocalDbKnowledgeService()
    knowledge.delete_upload_chunks(source_kind="tender", source_file=name)
    return LocalDbFileActionResponse(success=True, message="删除成功")
  except HTTPException as exc:
    return LocalDbFileActionResponse(success=False, message=str(exc.detail))
  except Exception as exc:
    return LocalDbFileActionResponse(success=False, message=str(exc))


@router.delete("/bid/delete", response_model=LocalDbFileActionResponse)
async def delete_bid_file(name: str = Query(..., description="文件名")):
  try:
    path = get_localdb_file_path("bid", name)
    os.remove(path)
    knowledge = LocalDbKnowledgeService()
    knowledge.delete_upload_chunks(source_kind="bid", source_file=name)
    return LocalDbFileActionResponse(success=True, message="删除成功")
  except HTTPException as exc:
    return LocalDbFileActionResponse(success=False, message=str(exc.detail))
  except Exception as exc:
    return LocalDbFileActionResponse(success=False, message=str(exc))


@router.get("/tender/download")
async def download_tender_file(name: str = Query(..., description="文件名")):
  path = get_localdb_file_path("tender", name)
  return FileResponse(path, filename=safe_localdb_filename(name), media_type=guess_mime_type(name))


@router.get("/bid/download")
async def download_bid_file(name: str = Query(..., description="文件名")):
  path = get_localdb_file_path("bid", name)
  return FileResponse(path, filename=safe_localdb_filename(name), media_type=guess_mime_type(name))


@router.post("/company/save")
async def save_company_info(request: LocalDbCompanyInfoRequest):
  """
  保存公司基本信息到本地知识库。
  前端“确认”时调用，生成时会自动纳入参考资料。
  """
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
    knowledge = LocalDbKnowledgeService()
    knowledge.upsert_company_chunks(company_text=company_text, mtime=now_mtime_str())
    return {"success": True, "message": "公司基本信息已保存", "mtime": now_mtime_str()}
  except Exception as exc:
    return {"success": False, "message": str(exc)}

