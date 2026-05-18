"""公司本地数据库目录：按 company_id 隔离（default 兼容旧版扁平目录）。"""

import os
import re

from ..config import settings


def sanitize_company_id(company_id: str) -> str:
    """校验并规范化 company_id；非法则抛出 ValueError。"""
    raw = (company_id or "").strip()
    if not raw or raw == "default":
        return "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw):
        raise ValueError("company_id 仅允许字母、数字、下划线、连字符，长度 1～64")
    return raw


def localdb_company_root(company_id: str) -> str:
    """某公司在磁盘上的根目录（其下含 tender/、bid/、knowledge.json）。"""
    cid = sanitize_company_id(company_id)
    base = os.path.join(settings.upload_dir, "localdb")
    if cid == "default":
        return base
    return os.path.join(base, "companies", cid)


def localdb_target_dir(company_id: str, doc_kind: str) -> str:
    """资料文件 / 公司基本信息 等落盘目录（兼容历史 tender、bid 子目录）。"""
    return os.path.join(localdb_company_root(company_id), doc_kind)


# 统一资料库目录；历史 tender/bid 仍可读
LOCALDB_FILES_DIR = "files"
LOCALDB_LEGACY_DIRS = ("tender", "bid")
LOCALDB_ALL_FILE_DIRS = (LOCALDB_FILES_DIR,) + LOCALDB_LEGACY_DIRS
LOCALDB_KNOWLEDGE_FILE_KIND = "file"
LOCALDB_TEMPLATE_DIR = "template"
LOCALDB_TEMPLATE_FILENAME = "export_template.docx"
LOCALDB_EXTRACTED_DIR = "_extracted"


def localdb_extracted_images_dir(company_id: str, source_filename: str) -> str:
    """某资料文件对应的内嵌图片导出目录（按源文件名分文件夹）。"""
    stem = os.path.splitext(os.path.basename(source_filename or "document"))[0]
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff.\-]+", "_", stem).strip("._")[:80] or "document"
    return os.path.join(
        localdb_company_root(company_id), LOCALDB_EXTRACTED_DIR, safe_stem
    )


def localdb_template_path(company_id: str) -> str:
    """该公司投标 Word 导出模板路径（固定文件名）。"""
    return os.path.join(
        localdb_target_dir(company_id, LOCALDB_TEMPLATE_DIR),
        LOCALDB_TEMPLATE_FILENAME,
    )


def localdb_template_exists(company_id: str) -> bool:
    return os.path.isfile(localdb_template_path(company_id))
