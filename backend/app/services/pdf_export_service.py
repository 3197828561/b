"""Word 标书导出后转 PDF（依赖 LibreOffice）。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid

from .file_service import FileService

logger = logging.getLogger(__name__)


def convert_docx_bytes_to_pdf(docx_bytes: bytes) -> bytes:
    """将 docx 字节转为 PDF 字节。"""
    soffice = FileService._find_libreoffice_executable()
    if not soffice:
        raise Exception(
            "未检测到 LibreOffice，无法导出 PDF。"
            "请安装 LibreOffice 或设置环境变量 LIBREOFFICE_PATH。"
        )

    work = tempfile.mkdtemp(prefix="bid_pdf_")
    docx_path = os.path.join(work, f"export_{uuid.uuid4().hex}.docx")
    try:
        with open(docx_path, "wb") as fh:
            fh.write(docx_bytes)

        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            work,
            os.path.abspath(docx_path),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise Exception(detail or f"LibreOffice 退出码 {proc.returncode}")

        base = os.path.splitext(os.path.basename(docx_path))[0]
        pdf_path = os.path.join(work, f"{base}.pdf")
        if not os.path.isfile(pdf_path):
            for fn in os.listdir(work):
                if fn.lower().endswith(".pdf"):
                    pdf_path = os.path.join(work, fn)
                    break
        if not os.path.isfile(pdf_path):
            raise Exception("LibreOffice 转换后未生成 PDF 文件")

        with open(pdf_path, "rb") as fh:
            return fh.read()
    finally:
        shutil.rmtree(work, ignore_errors=True)
