"""文档处理相关 API 路由。"""

import io
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from urllib.parse import quote

from ..models.schemas import (
    AnalysisRequest,
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    ComplianceIssueItem,
    CoverageCheckRequest,
    CoverageCheckResponse,
    FileUploadResponse,
    ScoringItemsRequest,
    ScoringItemsResponse,
    TechnicalRequirementGroup,
    WordExportRequest,
)
from ..services.file_service import FileService
from ..services.analysis_service import AnalysisService
from ..services.compliance_service import ComplianceService
from ..services.coverage_service import check_scoring_coverage
from ..services.outline_service import OutlineService
from ..services.pdf_export_service import convert_docx_bytes_to_pdf
from ..services.word_export_service import WordExportService
from ..utils.errors import AppError
from ..utils.sse import sse_chunk, sse_done, sse_error, sse_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/document", tags=["文档处理"])


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传文档文件并提取文本内容。"""
    try:
        if not FileService.is_supported_document(file.content_type, file.filename):
            return FileUploadResponse(
                success=False, message=FileService.SUPPORTED_DOCUMENTS_MESSAGE
            )

        file_content = await FileService.process_uploaded_file(file)
        return FileUploadResponse(
            success=True,
            message=f"文件 {file.filename} 上传成功",
            file_content=file_content,
        )
    except Exception as exc:
        logger.exception("文件上传失败")
        return FileUploadResponse(success=False, message=f"文件处理失败: {exc}")


@router.post("/analyze-stream")
async def analyze_document_stream(request: AnalysisRequest):
    """流式分析文档内容。"""
    try:
        analysis_service = AnalysisService()
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    async def generate():
        try:
            async for chunk in analysis_service.stream_document_analysis(
                file_content=request.file_content,
                analysis_type=request.analysis_type.value,
            ):
                yield sse_chunk(chunk)
        except AppError as exc:
            yield sse_error(exc.message)
        except Exception:
            logger.exception("文档分析失败")
            yield sse_error("文档分析失败，请稍后重试")
        finally:
            yield sse_done()

    return sse_response(generate())


@router.post("/scoring-items", response_model=ScoringItemsResponse)
async def extract_scoring_items(request: ScoringItemsRequest):
    """从已解析的技术评分要求中提取评分大类（用于目录映射与覆盖检查）。"""
    try:
        if not (request.requirements or "").strip():
            return ScoringItemsResponse(
                success=False, message="技术评分要求为空，请先完成标书解析"
            )
        outline_service = OutlineService()
        raw_groups = await outline_service._extract_requirement_groups(
            request.requirements
        )
        groups = [
            g if isinstance(g, TechnicalRequirementGroup) else TechnicalRequirementGroup(**g)
            for g in raw_groups
        ]
        return ScoringItemsResponse(
            success=True,
            message=f"已提取 {len(groups)} 个评分项",
            groups=groups,
        )
    except Exception as exc:
        logger.exception("评分项提取失败")
        return ScoringItemsResponse(success=False, message=str(exc))


@router.post("/coverage-check", response_model=CoverageCheckResponse)
async def coverage_check(request: CoverageCheckRequest):
    """检查目录末级章节是否覆盖全部评分项。"""
    try:
        groups_payload = [g.model_dump() for g in request.groups]
        outline_payload = [o.model_dump() for o in request.outline]
        result = check_scoring_coverage(groups_payload, outline_payload)
        uncovered = [TechnicalRequirementGroup(**g) for g in result["uncovered"]]
        rate_pct = int(result["coverage_rate"] * 100)
        msg = (
            f"覆盖 {result['covered_count']}/{result['total']} 项评分要求（{rate_pct}%）"
            if result["total"]
            else "未配置评分项，跳过检查"
        )
        return CoverageCheckResponse(
            success=True,
            message=msg,
            total=result["total"],
            covered_count=result["covered_count"],
            uncovered_count=result["uncovered_count"],
            coverage_rate=result["coverage_rate"],
            leaf_count=result["leaf_count"],
            uncovered=uncovered,
        )
    except Exception as exc:
        logger.exception("覆盖检查失败")
        return CoverageCheckResponse(success=False, message=str(exc))


@router.post("/export-word")
async def export_word(request: WordExportRequest):
    """根据目录数据导出 Word 文档。"""
    try:
        buffer, headers = WordExportService.export_outline(request)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers,
        )
    except Exception as exc:
        logger.exception("导出 Word 失败")
        raise HTTPException(status_code=500, detail=f"导出Word失败: {exc}") from exc


@router.post("/export-pdf")
async def export_pdf(request: WordExportRequest):
    """导出 PDF（先生成 Word 再经 LibreOffice 转换）。"""
    try:
        docx_buffer, _headers = WordExportService.export_outline(request)
        pdf_bytes = convert_docx_bytes_to_pdf(docx_buffer.getvalue())
        filename = f"{request.project_name or '标书文档'}.pdf"
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        }
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers=headers,
        )
    except Exception as exc:
        logger.exception("导出 PDF 失败")
        raise HTTPException(status_code=500, detail=f"导出PDF失败: {exc}") from exc


@router.post("/compliance-check", response_model=ComplianceCheckResponse)
async def compliance_check(request: ComplianceCheckRequest):
    """标书合规终检（AI + 规则）。"""
    try:
        groups = [g.model_dump() for g in request.scoring_groups]
        outline = [o.model_dump() for o in request.outline]
        service = ComplianceService()
        result = await service.run_check(
            project_overview=request.project_overview,
            tech_requirements=request.tech_requirements,
            scoring_groups=groups,
            outline=outline,
        )
        return ComplianceCheckResponse(
            success=True,
            message="合规检查完成",
            passed=result.passed,
            risk_level=result.risk_level,
            summary=result.summary,
            issues=[ComplianceIssueItem(**i.model_dump()) for i in result.issues],
            coverage_rate=result.coverage_rate,
            uncovered_scoring_count=result.uncovered_scoring_count,
        )
    except Exception as exc:
        logger.exception("合规检查失败")
        return ComplianceCheckResponse(success=False, message=str(exc), passed=False)
