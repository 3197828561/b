"""数据模型定义"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ConfigRequest(BaseModel):
    """OpenAI配置请求"""

    model_config = {"protected_namespaces": ()}

    api_key: str = Field(..., description="OpenAI API密钥")
    base_url: Optional[str] = Field("https://api.deepseek.com", description="Base URL")
    model_name: str = Field("deepseek-chat", description="模型名称")


class ConfigResponse(BaseModel):
    """配置响应"""

    success: bool
    message: str


class ModelListResponse(BaseModel):
    """模型列表响应"""

    models: List[str]
    success: bool
    message: str = ""


class FileUploadResponse(BaseModel):
    """文件上传响应"""

    success: bool
    message: str
    file_content: Optional[str] = None
    old_outline: Optional[str] = None


class LocalDbFileUploadResponse(BaseModel):
    """公司本地数据库文件上传响应"""

    success: bool
    message: str
    file_path: Optional[str] = None
    ocr_applied: bool = False
    ocr_char_count: int = 0


class LocalDbFileInfo(BaseModel):
    """公司本地数据库中文件信息"""

    name: str
    size_bytes: int
    mtime: str


class LocalDbFileListResponse(BaseModel):
    """公司本地数据库文件列表响应"""

    success: bool
    message: str
    files: List[LocalDbFileInfo] = Field(default_factory=list)


class LocalDbFileActionResponse(BaseModel):
    """公司本地数据库文件操作（删除/保存等）响应"""

    success: bool
    message: str


class LocalDbRebuildFileResult(BaseModel):
    """单文件重建结果"""

    name: str
    source_kind: str
    success: bool
    char_count: int = 0
    ocr_applied: bool = False
    error: Optional[str] = None


class LocalDbRebuildResponse(BaseModel):
    """知识库重建响应"""

    success: bool
    message: str
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    ocr_files: int = 0
    total_chars: int = 0
    cleared_chunks: int = 0
    file_results: List[LocalDbRebuildFileResult] = Field(default_factory=list)


class AnalysisType(str, Enum):
    """分析类型"""

    OVERVIEW = "overview"
    REQUIREMENTS = "requirements"


class OutlineMode(str, Enum):
    """目录生成模式。"""

    FREE = "free"
    ALIGNED = "aligned"


class AnalysisRequest(BaseModel):
    """文档分析请求"""

    file_content: str = Field(..., description="文档内容")
    analysis_type: AnalysisType = Field(..., description="分析类型")


class OutlineItem(BaseModel):
    """目录项"""

    id: str
    title: str
    description: str
    source_requirement_id: Optional[str] = None
    source_requirement_title: Optional[str] = None
    children: Optional[List["OutlineItem"]] = None
    content: Optional[str] = None


# 解决循环引用
OutlineItem.model_rebuild()


class OutlineResponse(BaseModel):
    """目录响应"""

    outline: List[OutlineItem]


class OutlineChildrenResponse(BaseModel):
    """指定一级目录下的子目录响应。"""

    children: List[OutlineItem]


class OutlineReviewResponse(BaseModel):
    """目录审核响应。"""

    passed: bool
    suggestions: List[str] = Field(default_factory=list)


class TechnicalRequirementGroup(BaseModel):
    """技术评分大类。"""

    requirement_id: str
    title: str
    description: str
    detail_points: List[str] = Field(default_factory=list)


class TechnicalRequirementGroupResponse(BaseModel):
    """技术评分大类提取响应。"""

    groups: List[TechnicalRequirementGroup]


class OutlineRequest(BaseModel):
    """目录生成请求"""

    overview: str = Field(..., description="项目概述")
    requirements: str = Field(..., description="技术评分要求")
    mode: OutlineMode = Field(OutlineMode.FREE, description="目录生成模式")
    uploaded_expand: Optional[bool] = Field(False, description="是否已上传方案扩写文件")
    old_outline: Optional[str] = Field(
        None, description="上传的方案扩写文件解析出的旧目录JSON"
    )
    old_document: Optional[str] = Field(
        None, description="上传的方案扩写文件解析出的旧文档"
    )


class ContentGenerationRequest(BaseModel):
    """内容生成请求"""

    outline: Dict[str, Any] = Field(..., description="目录结构")
    project_overview: str = Field("", description="项目概述")


class ChapterContentRequest(BaseModel):
    """单章节内容生成请求"""

    chapter: Dict[str, Any] = Field(..., description="章节信息")
    parent_chapters: Optional[List[Dict[str, Any]]] = Field(
        None, description="上级章节列表"
    )
    sibling_chapters: Optional[List[Dict[str, Any]]] = Field(
        None, description="同级章节列表"
    )
    project_overview: str = Field("", description="项目概述")
    localdb_company_id: str = Field(
        "default",
        min_length=1,
        max_length=64,
        description="本地知识库公司隔离 ID，与 /api/localdb 的 company_id 一致",
    )
    company_display_name: Optional[str] = Field(
        None,
        max_length=200,
        description="当前投标主体显示名称，用于正文差异化与检索增强；与侧栏公司名称一致",
    )
    chapter_word_count_min: int = Field(
        800,
        ge=50,
        le=100_000,
        description="单章节期望正文字数下限（提示模型用）",
    )
    chapter_word_count_max: int = Field(
        2500,
        ge=50,
        le=200_000,
        description="单章节期望正文字数上限（提示模型用）",
    )

    book_word_count_min: Optional[int] = Field(
        None,
        ge=1000,
        le=5_000_000,
        description="全书正文目标总字数下限（可选，用于提示模型整体体量）",
    )
    book_word_count_max: Optional[int] = Field(
        None,
        ge=1000,
        le=10_000_000,
        description="全书正文目标总字数上限（可选）",
    )
    leaf_chapter_index: Optional[int] = Field(
        None,
        ge=1,
        description="当前章节在全部末级章节中的序号（从 1 开始，可选）",
    )
    leaf_chapter_total: Optional[int] = Field(
        None,
        ge=1,
        description="末级章节总数（可选）",
    )

    @field_validator("localdb_company_id", mode="before")
    @classmethod
    def _norm_localdb_company_id(cls, v: object) -> str:
        from ..utils.localdb_paths import sanitize_company_id

        if v is None or (isinstance(v, str) and v.strip() == ""):
            return "default"
        if not isinstance(v, str):
            raise TypeError("localdb_company_id 须为字符串")
        return sanitize_company_id(v)

    @field_validator("company_display_name", mode="before")
    @classmethod
    def _norm_company_display_name(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise TypeError("company_display_name 须为字符串")
        s = v.strip()
        return s if s else None

    @model_validator(mode="after")
    def validate_chapter_and_book_word_counts(self) -> "ChapterContentRequest":
        if self.chapter_word_count_min > self.chapter_word_count_max:
            raise ValueError("chapter_word_count_min 不能大于 chapter_word_count_max")
        bm = self.book_word_count_min
        bx = self.book_word_count_max
        li = self.leaf_chapter_index
        lt = self.leaf_chapter_total
        book_any = bm is not None or bx is not None or li is not None or lt is not None
        if not book_any:
            return self
        if bm is None or bx is None:
            raise ValueError("若填写全书字数，需同时提供 book_word_count_min 与 book_word_count_max")
        if bm > bx:
            raise ValueError("book_word_count_min 不能大于 book_word_count_max")
        if li is None or lt is None:
            raise ValueError("若填写全书字数，需同时提供 leaf_chapter_index 与 leaf_chapter_total")
        if li > lt:
            raise ValueError("leaf_chapter_index 不能大于 leaf_chapter_total")
        return self


class ErrorResponse(BaseModel):
    """错误响应"""

    error: str
    detail: Optional[str] = None


class WordExportOutlineItem(BaseModel):
    """Word 导出用目录项。"""

    id: str
    title: str
    description: Optional[str] = None
    children: Optional[List["WordExportOutlineItem"]] = None
    content: Optional[str] = None


WordExportOutlineItem.model_rebuild()


class WordExportRequest(BaseModel):
    """Word导出请求"""

    project_name: Optional[str] = Field(None, description="项目名称")
    project_overview: Optional[str] = Field(None, description="项目概述")
    outline: List[WordExportOutlineItem] = Field(..., description="目录结构，包含内容")
    localdb_company_id: Optional[str] = Field(
        "default", description="使用该公司本地库中的 Word 导出模板（若有）"
    )
    insert_localdb_images: bool = Field(
        True, description="是否在资质/业绩等章节后插入本地库导出的内嵌图片"
    )
    max_images_per_chapter: int = Field(
        4, ge=0, le=20, description="每章最多插入图片张数"
    )
    include_appendices: bool = Field(
        False, description="是否在文末追加已填写的投标附录（投标函等）"
    )
    appendix_template_names: Optional[List[str]] = Field(
        None, description="指定附录模板文件名列表，空则全部"
    )


class ComplianceCheckRequest(BaseModel):
    """标书合规终检请求"""

    project_overview: str = ""
    tech_requirements: str = ""
    scoring_groups: List[TechnicalRequirementGroup] = Field(default_factory=list)
    outline: List[OutlineItem] = Field(default_factory=list)


class ComplianceIssueItem(BaseModel):
    severity: str = "中"
    category: str = ""
    message: str = ""
    suggestion: str = ""


class ComplianceCheckResponse(BaseModel):
    success: bool = True
    message: str = ""
    passed: bool = True
    risk_level: str = "低"
    summary: str = ""
    issues: List[ComplianceIssueItem] = Field(default_factory=list)
    coverage_rate: float = 1.0
    uncovered_scoring_count: int = 0


class ScoringItemsRequest(BaseModel):
    """从评分要求文本提取评分项"""

    requirements: str = Field(..., description="技术评分要求全文")


class ScoringItemsResponse(BaseModel):
    """评分项提取结果"""

    success: bool
    message: str = ""
    groups: List[TechnicalRequirementGroup] = Field(default_factory=list)


class CoverageCheckRequest(BaseModel):
    """目录覆盖检查请求"""

    groups: List[TechnicalRequirementGroup] = Field(default_factory=list)
    outline: List[OutlineItem] = Field(default_factory=list)


class CoverageCheckResponse(BaseModel):
    """目录覆盖检查结果"""

    success: bool
    message: str = ""
    total: int = 0
    covered_count: int = 0
    uncovered_count: int = 0
    coverage_rate: float = 0.0
    leaf_count: int = 0
    uncovered: List[TechnicalRequirementGroup] = Field(default_factory=list)


class LocalDbTemplateInfoResponse(BaseModel):
    """投标 Word 模板状态"""

    success: bool
    message: str
    exists: bool = False
    filename: Optional[str] = None
    size_bytes: int = 0
    mtime: Optional[str] = None
