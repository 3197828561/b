"""文件处理服务"""

import aiofiles
import os
import shutil
import subprocess
import time
import gc
import io
import logging
import tempfile
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple
import PyPDF2
import docx
from fastapi import UploadFile
import aiohttp
import asyncio
from ..config import settings

logger = logging.getLogger(__name__)

# 新增的第三方库
try:
    import pdfplumber
    import fitz  # PyMuPDF
    from docx2python import docx2python
    from PIL import Image

    HAS_ADVANCED_LIBS = True
except ImportError as e:
    HAS_ADVANCED_LIBS = False
    logger.warning("高级文档处理库未安装: %s", e)


class FileService:
    """文件处理服务"""

    OLE_COMPOUND_HEADER = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"

    SUPPORTED_DOCUMENTS_MESSAGE = (
        "支持 PDF、Word（.doc/.docx）、WPS（.wps/.wpt）、RTF、ODT、TXT 等；"
        "旧版 .doc/.wps 等可尝试自动转换（需本机 Microsoft Word 或 LibreOffice）"
    )

    ALLOWED_DOCUMENT_TYPES = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/rtf",
        "text/rtf",
        "text/plain",
        "application/vnd.oasis.opendocument.text",
        # WPS/部分浏览器或中转服务可能上报的 MIME
        "application/wps-office.docx",
        "application/wps-office.doc",
        "application/wps-office.wps",
        "application/wps-office.wpt",
    }
    ALLOWED_DOCUMENT_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".wps",
        ".wpt",
        ".dot",
        ".dotx",
        ".rtf",
        ".odt",
        ".txt",
        ".text",
        ".md",
    }
    WORD_LIKE_EXTENSIONS = {
        ".doc",
        ".docx",
        ".wps",
        ".wpt",
        ".dot",
        ".dotx",
        ".rtf",
        ".odt",
    }

    # 图片上传配置
    IMAGE_UPLOAD_URL = "https://mt.agnet.top/image/upload"
    IMAGE_UPLOAD_TIMEOUT = 30  # 超时时间（秒）

    @staticmethod
    def is_supported_document(
        content_type: str | None, filename: str | None = None
    ) -> bool:
        """判断上传文件类型是否受支持（优先 MIME，兜底文件扩展名）。"""
        normalized_content_type = (
            content_type.split(";", 1)[0].strip().lower() if content_type else None
        )
        if (
            normalized_content_type
            and normalized_content_type in FileService.ALLOWED_DOCUMENT_TYPES
        ):
            return True

        if filename:
            _, ext = os.path.splitext(filename.lower())
            if ext in FileService.ALLOWED_DOCUMENT_EXTENSIONS:
                return True

        return False

    @staticmethod
    def _get_document_kind(content_type: str | None, filename: str | None) -> str | None:
        """返回文档类型：pdf / docx。"""
        normalized_content_type = (
            content_type.split(";", 1)[0].strip().lower() if content_type else None
        )
        if normalized_content_type == "application/pdf":
            return "pdf"
        if normalized_content_type in {
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/rtf",
            "text/rtf",
            "application/vnd.oasis.opendocument.text",
            "application/wps-office.docx",
            "application/wps-office.doc",
            "application/wps-office.wps",
            "application/wps-office.wpt",
        }:
            return "docx"
        if normalized_content_type == "text/plain":
            return "text"

        # 部分浏览器或环境会给出 application/octet-stream，使用扩展名兜底
        if filename:
            _, ext = os.path.splitext(filename.lower())
            if ext == ".pdf":
                return "pdf"
            if ext in {".txt", ".text", ".md"}:
                return "text"
            if ext in FileService.WORD_LIKE_EXTENSIONS or ext == ".docx":
                return "docx"

        return None

    @staticmethod
    def _read_file_header(file_path: str, size: int = 512) -> bytes:
        with open(file_path, "rb") as fh:
            return fh.read(size)

    @staticmethod
    def _sniff_binary_kind(header: bytes, filename: str | None) -> str:
        """pdf | zip_office | ole | rtf | plaintext | markup | word_guess | unknown"""
        h = header or b""
        _, ext = os.path.splitext((filename or "").lower())
        if h.startswith(b"%PDF"):
            return "pdf"
        if h.startswith(b"PK"):
            return "zip_office"
        if h.startswith(FileService.OLE_COMPOUND_HEADER):
            return "ole"
        if h.startswith((b"{\\rtf", b"{\\RTF")):
            return "rtf"
        stripped = h.lstrip()
        if stripped.startswith(
            (b"<?xml", b"<html", b"<HTML", b"<w:", b"<W:")
        ):
            return "markup"
        if ext in {".txt", ".text", ".md", ".csv"}:
            return "plaintext"
        if ext == ".pdf":
            return "pdf"
        if ext == ".rtf":
            return "rtf"
        if ext in FileService.WORD_LIKE_EXTENSIONS:
            return "word_guess"
        return "unknown"

    @staticmethod
    def _extract_plain_text(file_path: str) -> str:
        with open(file_path, "rb") as fh:
            raw = fh.read()
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _extract_rtf_text(file_path: str) -> str:
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError as exc:
            raise Exception(
                "RTF 解析依赖 striprtf，请执行: pip install -r backend/requirements.txt"
            ) from exc
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            return rtf_to_text(fh.read()).strip()

    @staticmethod
    def _find_libreoffice_executable() -> Optional[str]:
        env_path = os.environ.get("LIBREOFFICE_PATH") or os.environ.get("SOFFICE_PATH")
        if env_path and os.path.isfile(env_path):
            return env_path
        if os.name == "nt":
            for candidate in (
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ):
                if os.path.isfile(candidate):
                    return candidate
        return shutil.which("soffice") or shutil.which("libreoffice")

    @staticmethod
    def _convert_to_docx_via_libreoffice(input_path: str) -> tuple[str, list[str]]:
        soffice = FileService._find_libreoffice_executable()
        if not soffice:
            raise Exception(
                "未检测到 LibreOffice，无法自动转换该文档。"
                "请安装 LibreOffice，或将文件另存为 .docx / .pdf 后上传。"
            )
        out_dir = tempfile.mkdtemp(prefix="lo_convert_")
        cleanup_dirs = [out_dir]
        try:
            cmd = [
                soffice,
                "--headless",
                "--norestore",
                "--convert-to",
                "docx",
                "--outdir",
                out_dir,
                os.path.abspath(input_path),
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
            base = os.path.splitext(os.path.basename(input_path))[0]
            preferred = os.path.join(out_dir, f"{base}.docx")
            if os.path.isfile(preferred):
                return preferred, cleanup_dirs
            for fn in os.listdir(out_dir):
                if fn.lower().endswith(".docx"):
                    return os.path.join(out_dir, fn), cleanup_dirs
            raise Exception("LibreOffice 转换后未生成 .docx 文件")
        except Exception:
            shutil.rmtree(out_dir, ignore_errors=True)
            raise

    @staticmethod
    def _convert_to_docx(input_path: str) -> tuple[str, list[str]]:
        """将 Office 文档转为临时 docx，返回 (docx路径, 需清理的路径或目录)。"""
        cleanup: list[str] = []
        if os.name == "nt":
            try:
                converted = FileService._convert_doc_to_docx_windows(input_path)
                cleanup.append(converted)
                return converted, cleanup
            except Exception as exc:
                logger.warning("Word COM 转换失败，尝试 LibreOffice: %s", exc)
        docx_path, lo_cleanup = FileService._convert_to_docx_via_libreoffice(input_path)
        cleanup.extend(lo_cleanup)
        return docx_path, cleanup

    @staticmethod
    def _cleanup_temp_paths(paths: list[str]) -> None:
        for path in paths:
            if not path:
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                FileService._safe_file_cleanup(path)

    @staticmethod
    def _pick_ocr_docx_path(original_path: str, cleanup_paths: list[str]) -> str:
        for path in reversed(cleanup_paths):
            if path.lower().endswith(".docx") and os.path.isfile(path):
                return path
        return original_path

    @staticmethod
    async def extract_localdb_document_text_from_path(
        file_path: str,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> tuple[str, str, list[str]]:
        """
        从磁盘文件抽取正文（本地库 RAG）。
        返回 (文本, OCR用类型 pdf/docx/text, 临时路径列表供清理)。
        """
        header = FileService._read_file_header(file_path)
        binary_kind = FileService._sniff_binary_kind(header, filename)
        doc_kind = FileService._get_document_kind(content_type, filename)
        cleanup: list[str] = []
        ocr_kind = doc_kind or ("pdf" if binary_kind == "pdf" else "docx")

        try:
            if binary_kind == "pdf" or doc_kind == "pdf":
                text = await FileService.extract_text_from_pdf(file_path)
                return text, "pdf", cleanup

            if binary_kind == "plaintext" or doc_kind == "text":
                return FileService._extract_plain_text(file_path), "text", cleanup

            if binary_kind == "rtf":
                return FileService._extract_rtf_text(file_path), "docx", cleanup

            if binary_kind == "zip_office":
                try:
                    text = await FileService.extract_text_from_docx(file_path)
                    return text, "docx", cleanup
                except Exception:
                    docx_path, extra = FileService._convert_to_docx(file_path)
                    cleanup.extend(extra)
                    text = await FileService.extract_text_from_docx(docx_path)
                    return text, "docx", cleanup

            if binary_kind == "ole":
                docx_path, extra = FileService._convert_to_docx(file_path)
                cleanup.extend(extra)
                text = await FileService.extract_text_from_docx(docx_path)
                return text, "docx", cleanup

            if binary_kind in {"markup", "word_guess", "unknown"}:
                docx_path, extra = FileService._convert_to_docx(file_path)
                cleanup.extend(extra)
                text = await FileService.extract_text_from_docx(docx_path)
                return text, "docx", cleanup

            raise Exception(FileService.SUPPORTED_DOCUMENTS_MESSAGE)
        except Exception as exc:
            FileService._cleanup_temp_paths(cleanup)
            if "不支持的文件" in str(exc) or "支持 PDF" in str(exc):
                raise
            raise Exception(
                f"无法读取该文档：{exc}。{FileService.SUPPORTED_DOCUMENTS_MESSAGE}"
            ) from exc

    @staticmethod
    async def upload_image_to_server(image_data: bytes, filename: str) -> Optional[str]:
        """上传图片到外部服务器"""
        try:
            # 准备multipart/form-data格式的数据
            form_data = aiohttp.FormData()
            form_data.add_field(
                "file",
                io.BytesIO(image_data),
                filename=filename,
                content_type="image/jpeg",
            )

            timeout = aiohttp.ClientTimeout(total=FileService.IMAGE_UPLOAD_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    FileService.IMAGE_UPLOAD_URL, data=form_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        # 根据实际API返回格式获取图片URL
                        return result.get("file_url")
                    else:
                        logger.warning("图片上传失败，状态码: %s", response.status)
                        return None
        except Exception as e:
            logger.warning("图片上传异常: %s", e)
            return None

    @staticmethod
    def extract_images_from_pdf(file_path: str) -> List[Tuple[bytes, str, int, int]]:
        """从PDF提取图片，返回 (图片数据, 扩展名, 页码, 图片索引) 列表"""
        if not HAS_ADVANCED_LIBS:
            return []

        images = []
        try:
            doc = fitz.open(file_path)

            for page_num in range(doc.page_count):
                page = doc[page_num]
                image_list = page.get_images(full=True)

                for img_index, img in enumerate(image_list):
                    try:
                        # 获取图片数据
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)

                        # 转换为RGB格式（如果是CMYK）
                        if pix.n - pix.alpha < 4:
                            img_data = pix.tobytes("jpeg")
                            ext = "jpg"
                        else:
                            pix1 = fitz.Pixmap(fitz.csRGB, pix)
                            img_data = pix1.tobytes("jpeg")
                            ext = "jpg"
                            pix1 = None

                        pix = None
                        images.append((img_data, ext, page_num + 1, img_index + 1))

                    except Exception as e:
                        logger.warning(
                            "提取PDF第%s页图片%s失败: %s",
                            page_num + 1,
                            img_index + 1,
                            e,
                        )
                        continue

            doc.close()
            return images

        except Exception as e:
            logger.warning("PDF图片提取失败: %s", e)
            return []

    @staticmethod
    def extract_images_from_docx(file_path: str) -> List[Tuple[bytes, str, int]]:
        """从Word文档提取图片，返回 (图片数据, 扩展名, 图片索引) 列表"""
        images = []
        doc = None
        try:
            doc = docx.Document(file_path)

            # 获取文档中的所有关系
            rels = doc.part.rels
            img_index = 0

            for rel in rels.values():
                if "image" in rel.target_ref:
                    try:
                        # 读取图片数据
                        img_data = rel.target_part.blob

                        # 根据content_type确定扩展名
                        content_type = rel.target_part.content_type
                        if "jpeg" in content_type:
                            ext = "jpg"
                        elif "png" in content_type:
                            ext = "png"
                        elif "gif" in content_type:
                            ext = "gif"
                        elif "bmp" in content_type:
                            ext = "bmp"
                        else:
                            ext = "jpg"  # 默认

                        img_index += 1
                        images.append((img_data, ext, img_index))

                    except Exception as e:
                        logger.warning("提取Word文档图片%s失败: %s", img_index + 1, e)
                        continue

            if doc:
                del doc
            gc.collect()
            return images

        except Exception as e:
            if doc:
                del doc
            gc.collect()
            logger.warning("Word文档图片提取失败: %s", e)
            return []

    @staticmethod
    def save_localdb_extracted_images(
        company_id: str,
        source_filename: str,
        images: List[Tuple[bytes, str, int]],
    ) -> List[Tuple[str, int, bytes]]:
        """
        将 Word 内嵌图导出到公司本地库目录，供查阅与 OCR。
        返回 [(相对公司根目录的路径, 图片序号, 图片字节), ...]
        """
        from ..utils.localdb_paths import (
            localdb_company_root,
            localdb_extracted_images_dir,
        )

        if not images:
            return []

        out_dir = localdb_extracted_images_dir(company_id, source_filename)
        os.makedirs(out_dir, exist_ok=True)
        company_root = localdb_company_root(company_id)
        saved: List[Tuple[str, int, bytes]] = []

        for img_data, ext, img_index in images:
            ext_clean = (ext or "png").lstrip(".").lower() or "png"
            name = f"img_{img_index}.{ext_clean}"
            full_path = os.path.join(out_dir, name)
            with open(full_path, "wb") as fh:
                fh.write(img_data)
            rel_path = os.path.relpath(full_path, company_root).replace("\\", "/")
            saved.append((rel_path, img_index, img_data))

        return saved

    @staticmethod
    def remove_localdb_extracted_images(company_id: str, source_filename: str) -> None:
        """删除某资料文件对应的内嵌图导出目录。"""
        from ..utils.localdb_paths import localdb_extracted_images_dir

        out_dir = localdb_extracted_images_dir(company_id, source_filename)
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir, ignore_errors=True)

    @staticmethod
    def _safe_file_cleanup(file_path: str, max_retries: int = 3) -> bool:
        """安全删除文件，带重试机制"""
        for attempt in range(max_retries):
            try:
                if os.path.exists(file_path):
                    # 强制垃圾回收，释放可能的文件句柄
                    gc.collect()
                    time.sleep(0.1 * (attempt + 1))  # 递增延迟
                    os.remove(file_path)
                return True
            except OSError as e:
                if attempt == max_retries - 1:
                    logger.warning("无法删除文件 %s: %s", file_path, e)
                    return False
                time.sleep(0.5)  # 等待后重试
        return True

    @staticmethod
    async def save_uploaded_file(file: UploadFile) -> str:
        """保存上传的文件并返回文件路径"""
        # 创建上传目录
        os.makedirs(settings.upload_dir, exist_ok=True)

        # 生成带时间戳的文件名，防止重复
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 精确到毫秒
        filename = file.filename or "unknown_file"

        # 分离文件名和扩展名
        name, ext = os.path.splitext(filename)

        # 生成新的文件名：原文件名_时间戳.扩展名
        new_filename = f"{name}_{timestamp}{ext}"
        file_path = os.path.join(settings.upload_dir, new_filename)

        # 异步保存文件
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        return file_path

    @staticmethod
    async def extract_text_from_pdf(file_path: str) -> str:
        """从PDF文件提取文本，支持表格内容和图片"""
        if HAS_ADVANCED_LIBS:
            return await FileService._extract_pdf_with_pdfplumber(file_path)
        else:
            # 降级到原来的PyPDF2方法
            return FileService._extract_pdf_with_pypdf2(file_path)

    @staticmethod
    async def _extract_pdf_with_pdfplumber(file_path: str) -> str:
        """使用pdfplumber提取PDF文本，包含表格和图片（确保及时释放文件句柄）"""
        try:
            extracted_text = []
            image_references = []  # 存储图片引用映射
            global_img_counter = 1

            # 获取PDF文档的所有图片信息，用于后续匹配
            all_images = FileService.extract_images_from_pdf(file_path)
            page_images_map = {}
            for img_data, ext, page_num, img_index in all_images:
                if page_num not in page_images_map:
                    page_images_map[page_num] = []
                page_images_map[page_num].append((img_data, ext, img_index))

            # 使用上下文管理器，避免在Windows上产生文件锁
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # 添加页码标识
                    extracted_text.append(f"\n--- 第 {page_num} 页 ---\n")

                    # 提取普通文本
                    text = page.extract_text()
                    if text:
                        # 检查文本中是否有图片标记
                        import re

                        img_pattern = r"----.*?(?:image|img|media).*?----"
                        img_matches = list(
                            re.finditer(img_pattern, text, re.IGNORECASE)
                        )

                        if img_matches and page_num in page_images_map:
                            # 按顺序处理页面中的图片
                            page_images = page_images_map[page_num]
                            processed_text = text

                            for i, match in enumerate(img_matches):
                                if i < len(page_images):
                                    # 获取对应的图片数据
                                    img_data, ext, img_index = page_images[i]
                                    filename = (
                                        f"pdf_page{page_num}_img{img_index}.{ext}"
                                    )

                                    # 上传图片
                                    image_url = (
                                        await FileService.upload_image_to_server(
                                            img_data, filename
                                        )
                                    )

                                    if image_url:
                                        # 替换图片标记
                                        old_mark = match.group()
                                        new_mark = f"[图片{global_img_counter}]"
                                        processed_text = processed_text.replace(
                                            old_mark, new_mark, 1
                                        )

                                        # 记录图片引用
                                        image_references.append(
                                            f"[图片{global_img_counter}]: {image_url}"
                                        )
                                        global_img_counter += 1

                            extracted_text.append(processed_text)
                        else:
                            extracted_text.append(text)

                    # 提取表格
                    tables = page.extract_tables()
                    for table_num, table in enumerate(tables, 1):
                        extracted_text.append(f"\n[表格 {table_num}]")
                        for row in table:
                            if row:  # 跳过空行
                                # 过滤空值并连接单元格
                                row_text = " | ".join(
                                    [str(cell) if cell else "" for cell in row]
                                )
                                extracted_text.append(row_text)
                        extracted_text.append("[表格结束]\n")

            # 在文档末尾添加图片引用映射
            if image_references:
                extracted_text.append(f"\n\n--- 图片引用 ---")
                extracted_text.extend(image_references)

            result = "\n".join(extracted_text).strip()
            gc.collect()
            return result
        except Exception as e:
            gc.collect()
            # 如果pdfplumber失败，尝试PyMuPDF
            try:
                return await FileService._extract_pdf_with_pymupdf(file_path)
            except Exception:
                raise Exception(f"PDF文件读取失败: {str(e)}")

    @staticmethod
    async def _extract_pdf_with_pymupdf(file_path: str) -> str:
        """使用PyMuPDF提取PDF文本和图片"""
        try:
            doc = fitz.open(file_path)
            extracted_text = []

            for page_num in range(doc.page_count):
                page = doc[page_num]
                extracted_text.append(f"\n--- 第 {page_num + 1} 页 ---\n")

                # 提取文本
                text = page.get_text()
                if text:
                    extracted_text.append(text)

                # 尝试提取表格
                try:
                    tables = page.find_tables()
                    for table_num, table in enumerate(tables, 1):
                        extracted_text.append(f"\n[表格 {table_num}]")
                        table_data = table.extract()
                        for row in table_data:
                            if row:
                                row_text = " | ".join(
                                    [str(cell) if cell else "" for cell in row]
                                )
                                extracted_text.append(row_text)
                        extracted_text.append("[表格结束]\n")
                except:
                    # 如果表格提取失败，跳过
                    pass

            doc.close()
            return "\n".join(extracted_text).strip()
        except Exception as e:
            raise Exception(f"PDF文件读取失败: {str(e)}")

    @staticmethod
    def _extract_pdf_with_pypdf2(file_path: str) -> str:
        """使用PyPDF2提取PDF文本（原方法）"""
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text.strip()
        except Exception as e:
            raise Exception(f"PDF文件读取失败: {str(e)}")

    @staticmethod
    async def extract_text_from_docx(file_path: str) -> str:
        """从Word文档提取文本，支持表格内容和图片"""
        if HAS_ADVANCED_LIBS:
            return await FileService._extract_docx_with_docx2python(file_path)
        else:
            # 降级到原来的python-docx方法，但增强表格处理
            return await FileService._extract_docx_with_python_docx(file_path)

    @staticmethod
    async def _extract_docx_with_docx2python(file_path: str) -> str:
        """使用docx2python提取Word文档内容和图片（确保及时释放文件句柄）"""
        try:
            extracted_text = []
            image_references = []  # 存储图片引用映射
            global_img_counter = 1

            # 获取Word文档的所有图片信息
            all_images = FileService.extract_images_from_docx(file_path)

            # 使用上下文管理器确保文件及时关闭，避免Windows上的锁定
            with docx2python(file_path) as content:
                # 处理文档内容
                if hasattr(content, "document"):
                    for section in content.document:
                        for element in section:
                            if isinstance(element, list):
                                # 这可能是表格
                                extracted_text.append("\n[表格内容]")
                                for row in element:
                                    if isinstance(row, list):
                                        row_text = " | ".join(
                                            [str(cell).strip() for cell in row if cell]
                                        )
                                        if row_text:
                                            extracted_text.append(row_text)
                                    else:
                                        extracted_text.append(str(row))
                                extracted_text.append("[表格结束]\n")
                            else:
                                # 普通文本，检查是否包含图片标记
                                text = str(element).strip()
                                if text:
                                    # 检查文本中是否有图片标记
                                    import re

                                    img_pattern = r"----.*?(?:image|img|media).*?----"
                                    img_matches = list(
                                        re.finditer(img_pattern, text, re.IGNORECASE)
                                    )

                                    if img_matches and all_images:
                                        processed_text = text

                                        for match in img_matches:
                                            if global_img_counter <= len(all_images):
                                                # 获取对应的图片数据
                                                img_data, ext, img_index = all_images[
                                                    global_img_counter - 1
                                                ]
                                                filename = f"docx_img{global_img_counter}.{ext}"

                                                # 上传图片
                                                image_url = await FileService.upload_image_to_server(
                                                    img_data, filename
                                                )

                                                if image_url:
                                                    # 替换图片标记
                                                    old_mark = match.group()
                                                    new_mark = (
                                                        f"[图片{global_img_counter}]"
                                                    )
                                                    processed_text = (
                                                        processed_text.replace(
                                                            old_mark, new_mark, 1
                                                        )
                                                    )

                                                    # 记录图片引用
                                                    image_references.append(
                                                        f"[图片{global_img_counter}]: {image_url}"
                                                    )
                                                    global_img_counter += 1

                                        extracted_text.append(processed_text)
                                    else:
                                        extracted_text.append(text)

            # 在文档末尾添加图片引用映射
            if image_references:
                extracted_text.append(f"\n\n--- 图片引用 ---")
                extracted_text.extend(image_references)

            result = "\n".join(extracted_text).strip()
            gc.collect()
            return result
        except Exception as e:
            gc.collect()
            # 如果docx2python失败，回退到增强的python-docx
            try:
                return await FileService._extract_docx_with_python_docx(file_path)
            except Exception:
                raise Exception(f"Word文档读取失败: {str(e)}")

    @staticmethod
    async def _extract_docx_with_python_docx(file_path: str) -> str:
        """使用python-docx提取Word文档内容和图片（增强版）"""
        doc = None
        try:
            doc = docx.Document(file_path)
            extracted_text = []
            image_references = []  # 存储图片引用映射
            global_img_counter = 1

            # 获取Word文档的所有图片信息
            all_images = FileService.extract_images_from_docx(file_path)

            # 提取段落文本，同时处理图片
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if text:
                    # 检查文本中是否有图片标记
                    import re

                    img_pattern = r"----.*?(?:image|img|media).*?----"
                    img_matches = list(re.finditer(img_pattern, text, re.IGNORECASE))

                    if img_matches and all_images:
                        processed_text = text

                        for match in img_matches:
                            if global_img_counter <= len(all_images):
                                # 获取对应的图片数据
                                img_data, ext, img_index = all_images[
                                    global_img_counter - 1
                                ]
                                filename = f"docx_img{global_img_counter}.{ext}"

                                # 上传图片
                                image_url = await FileService.upload_image_to_server(
                                    img_data, filename
                                )

                                if image_url:
                                    # 替换图片标记
                                    old_mark = match.group()
                                    new_mark = f"[图片{global_img_counter}]"
                                    processed_text = processed_text.replace(
                                        old_mark, new_mark, 1
                                    )

                                    # 记录图片引用
                                    image_references.append(
                                        f"[图片{global_img_counter}]: {image_url}"
                                    )
                                    global_img_counter += 1

                        extracted_text.append(processed_text)
                    else:
                        extracted_text.append(text)

            # 提取表格内容
            for table_num, table in enumerate(doc.tables, 1):
                extracted_text.append(f"\n[表格 {table_num}]")
                for row in table.rows:
                    row_data = []
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        row_data.append(cell_text if cell_text else "")
                    row_text = " | ".join(row_data)
                    if row_text.strip():
                        extracted_text.append(row_text)
                extracted_text.append("[表格结束]\n")

            # 在文档末尾添加图片引用映射
            if image_references:
                extracted_text.append(f"\n\n--- 图片引用 ---")
                extracted_text.extend(image_references)

            result = "\n".join(extracted_text).strip()

            # 确保释放资源
            if doc:
                del doc
            gc.collect()

            return result
        except Exception as e:
            # 确保释放资源
            if doc:
                del doc
            gc.collect()
            raise Exception(f"Word文档读取失败: {str(e)}")

    @staticmethod
    def _convert_doc_to_docx_windows(doc_path: str) -> str:
        """在 Windows 上通过 Word 将文档转为临时 .docx（支持 .doc/.wps 等 Word 可打开格式）。"""
        # 依赖本机安装的 Microsoft Word 与 pywin32
        if os.name != "nt":
            raise Exception("当前系统不支持 .doc 自动转换，请先另存为 .docx")

        try:
            import pythoncom
            import win32com.client  # type: ignore
        except ImportError:
            raise Exception(
                "当前环境未安装 pywin32，无法自动转换 .doc。请安装 pywin32 或先另存为 .docx"
            )

        temp_docx = os.path.join(
            tempfile.gettempdir(), f"doc_convert_{uuid.uuid4().hex}.docx"
        )
        word = None
        doc = None
        try:
            pythoncom.CoInitialize()
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(os.path.abspath(doc_path))
            # 16 = wdFormatDocumentDefault (.docx)
            doc.SaveAs2(os.path.abspath(temp_docx), FileFormat=16)
            return temp_docx
        except Exception as exc:
            raise Exception(
                f".doc 自动转换失败，请确认已安装 Microsoft Word，或先另存为 .docx。原因: {exc}"
            )
        finally:
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            try:
                if word is not None:
                    word.Quit()
            except Exception:
                pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    @staticmethod
    async def process_uploaded_file(file: UploadFile) -> str:
        """处理上传的文件并提取文本内容"""
        # 检查文件大小
        content = await file.read()
        if len(content) > settings.max_file_size:
            limit_mb = int(settings.max_file_size / 1024 / 1024)
            raise Exception(
                f"文件大小超过限制（最大 {limit_mb}MB）"
            )

        # 重置文件指针
        await file.seek(0)

        # 保存文件
        file_path = await FileService.save_uploaded_file(file)

        try:
            # 读取文件头，避免仅凭扩展名误判（例如 .doc 实际为旧二进制格式）
            file_header = b""
            try:
                with open(file_path, "rb") as fh:
                    file_header = fh.read(8)
            except Exception:
                file_header = b""

            if not FileService.is_supported_document(
                file.content_type, file.filename
            ):
                raise Exception(FileService.SUPPORTED_DOCUMENTS_MESSAGE)

            text, _ocr_kind, cleanup_paths = (
                await FileService.extract_localdb_document_text_from_path(
                    file_path,
                    content_type=file.content_type,
                    filename=file.filename,
                )
            )
            FileService._cleanup_temp_paths(cleanup_paths)

            # 成功提取后，使用安全的文件清理方法
            FileService._safe_file_cleanup(file_path)

            return text

        except Exception as e:
            # 异常情况下也使用安全的文件清理方法
            FileService._safe_file_cleanup(file_path)
            raise e
