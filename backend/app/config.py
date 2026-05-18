"""应用配置管理"""

try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """应用设置"""

    app_name: str = "昆山市尚为人力资源配置服务有限公司投标助手"
    app_version: str = "2.0.0"
    debug: bool = False
    enable_file_logging: bool = False

    # CORS设置
    cors_origins: list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3003",
        "http://localhost:3004",
        "http://127.0.0.1:3004",
    ]

    # 文件上传设置
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    upload_dir: str = "uploads"

    # 本地库扫描件 OCR（RAG 入库前补充文本）
    ocr_enabled: bool = True
    ocr_min_file_bytes: int = 80 * 1024  # 小于 80KB 不触发
    ocr_trigger_max_chars: int = 400  # 正文少于此字数则尝试 OCR
    ocr_skip_if_chars_ge: int = 2500  # 正文已足够则跳过
    ocr_large_file_bytes: int = 2 * 1024 * 1024  # 2MB 以上大文件
    ocr_large_file_min_chars: int = 3000  # 大文件但正文仍少于此则 OCR
    ocr_pdf_max_pages: int = 40
    ocr_pdf_zoom: float = 2.0
    ocr_docx_max_images: int = 60
    # 本地库：Word 内嵌图始终导出并 OCR（不受「正文已够长则跳过」限制）
    ocr_docx_embedded_always: bool = True

    # 本地库向量检索（OpenAI Embedding）
    embedding_enabled: bool = True
    embedding_model: str = "text-embedding-3-small"
    embedding_hybrid_weight: float = 0.55  # 向量分权重，其余为关键词分

    # OpenAI默认设置
    default_model: str = "gpt-3.5-turbo"

    class Config:
        env_file = ".env"


# 全局设置实例
settings = Settings()

# 确保上传目录存在
os.makedirs(settings.upload_dir, exist_ok=True)
