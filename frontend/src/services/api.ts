/**
 * API 服务与流式响应工具
 */
import axios from 'axios';
import { OutlineData, OutlineItem, OutlineMode, TechnicalRequirementGroup } from '../types';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

api.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);

export interface FileUploadResponse {
  success: boolean;
  message: string;
  file_content?: string;
  old_outline?: string;
}

export interface AnalysisRequest {
  file_content: string;
  analysis_type: 'overview' | 'requirements';
}

export interface OutlineRequest {
  overview: string;
  requirements: string;
  mode?: OutlineMode;
  uploaded_expand?: boolean;
  old_outline?: string;
  old_document?: string;
}

export interface ChapterContentRequest {
  chapter: OutlineItem;
  parent_chapters?: OutlineItem[];
  sibling_chapters?: OutlineItem[];
  project_overview: string;
  /** 单章节正文字数下限（一般由全书目标均摊得出） */
  chapter_word_count_min?: number;
  /** 单章节正文字数上限 */
  chapter_word_count_max?: number;
  /** 全书正文目标总字数下限（与 leaf 序号一并传，用于提示模型） */
  book_word_count_min?: number;
  book_word_count_max?: number;
  leaf_chapter_index?: number;
  leaf_chapter_total?: number;
  /** 与当前选择的公司一致，用于检索对应本地知识库 */
  localdb_company_id?: string;
  /** 侧栏显示的公司名称，用于正文绑定投标主体并与其它公司区分 */
  company_display_name?: string;
}

export interface WordExportRequest {
  project_name?: string;
  project_overview?: string;
  outline: OutlineItem[];
  localdb_company_id?: string;
  insert_localdb_images?: boolean;
  max_images_per_chapter?: number;
  include_appendices?: boolean;
}

export interface ScoringItemsResponse {
  success: boolean;
  message: string;
  groups: TechnicalRequirementGroup[];
}

export interface CoverageCheckResponse {
  success: boolean;
  message: string;
  total: number;
  covered_count: number;
  uncovered_count: number;
  coverage_rate: number;
  leaf_count: number;
  uncovered: TechnicalRequirementGroup[];
}

export interface ComplianceIssueItem {
  severity: string;
  category: string;
  message: string;
  suggestion: string;
}

export interface ComplianceCheckResponse {
  success: boolean;
  message: string;
  passed: boolean;
  risk_level: string;
  summary: string;
  issues: ComplianceIssueItem[];
  coverage_rate: number;
  uncovered_scoring_count: number;
}

export interface LocalDbTemplateInfoResponse {
  success: boolean;
  message: string;
  exists?: boolean;
  filename?: string | null;
  size_bytes?: number;
  mtime?: string | null;
}

export interface StreamEvent {
  type?: 'progress' | 'result';
  chunk?: string;
  outline?: OutlineData;
  error?: boolean;
  message?: string;
}

const formatErrorDetail = (detail: unknown): string | null => {
  if (!detail) {
    return null;
  }

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    const lines = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item;
        }

        if (item && typeof item === 'object') {
          const maybeItem = item as { loc?: Array<string | number>; msg?: string };
          const path = maybeItem.loc?.join(' -> ');
          return path ? `${path}: ${maybeItem.msg || '参数校验失败'}` : (maybeItem.msg || '参数校验失败');
        }

        return null;
      })
      .filter((line): line is string => Boolean(line));

    return lines.length > 0 ? lines.join('；') : null;
  }

  if (detail && typeof detail === 'object') {
    const maybeDetail = detail as { detail?: unknown; message?: string };
    return formatErrorDetail(maybeDetail.detail) || maybeDetail.message || JSON.stringify(detail);
  }

  return String(detail);
};

export const getErrorMessage = (error: unknown, fallback = '请求失败'): string => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    const message = error.response?.data?.message;
    return formatErrorDetail(detail) || message || error.message || fallback;
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  return fallback;
};

const ensureResponseOk = async (response: Response, fallback: string): Promise<Response> => {
  if (response.ok) {
    return response;
  }

  try {
    const data = await response.json();
    throw new Error(formatErrorDetail(data.detail) || data.message || fallback);
  } catch (error) {
    if (error instanceof Error && error.message !== 'Unexpected end of JSON input') {
      throw error;
    }
  }

  const text = await response.text();
  throw new Error(text || fallback);
};

export const readSseStream = async (
  response: Response,
  onEvent: (event: StreamEvent) => void,
  fallbackMessage: string
): Promise<void> => {
  await ensureResponseOk(response, fallbackMessage);

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('无法读取响应流');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';

    for (const eventBlock of events) {
      const dataLine = eventBlock
        .split('\n')
        .find((line) => line.startsWith('data: '));

      if (!dataLine) {
        continue;
      }

      const data = dataLine.slice(6);
      if (data === '[DONE]') {
        return;
      }

      let event: StreamEvent | null = null;
      try {
        event = JSON.parse(data) as StreamEvent;
      } catch {
        // 忽略非法片段，等待后续完整数据
        continue;
      }

      onEvent(event);
    }
  }
};

export const collectSseText = async (
  response: Response,
  onText?: (fullText: string, chunk: string) => void,
  fallbackMessage = '流式请求失败'
): Promise<string> => {
  let fullText = '';

  await readSseStream(
    response,
    (event) => {
      if (event.error) {
        throw new Error(event.message || fallbackMessage);
      }

      if (!event.chunk) {
        return;
      }

      fullText += event.chunk;
      onText?.(fullText, event.chunk);
    },
    fallbackMessage
  );

  return fullText;
};

const postJson = (path: string, data: unknown) =>
  fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });

export const documentApi = {
  uploadFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<FileUploadResponse>('/api/document/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },
  analyzeDocumentStream: (data: AnalysisRequest) => postJson('/api/document/analyze-stream', data),
  extractScoringItems: (requirements: string) =>
    api.post<ScoringItemsResponse>('/api/document/scoring-items', { requirements }),
  coverageCheck: (groups: TechnicalRequirementGroup[], outline: OutlineItem[]) =>
    api.post<CoverageCheckResponse>('/api/document/coverage-check', { groups, outline }),
  exportWord: async (data: WordExportRequest) =>
    ensureResponseOk(await postJson('/api/document/export-word', data), '导出失败'),
  exportPdf: async (data: WordExportRequest) =>
    ensureResponseOk(await postJson('/api/document/export-pdf', data), '导出 PDF 失败'),
  complianceCheck: (payload: {
    project_overview: string;
    tech_requirements: string;
    scoring_groups: TechnicalRequirementGroup[];
    outline: OutlineItem[];
  }) => api.post<ComplianceCheckResponse>('/api/document/compliance-check', payload),
};

export const outlineApi = {
  generateOutline: (data: OutlineRequest) => api.post<OutlineData>('/api/outline/generate', data),
  generateOutlineStream: (data: OutlineRequest) => postJson('/api/outline/generate-stream', data),
};

export const contentApi = {
  generateChapterContent: (data: ChapterContentRequest) => api.post<{ success: boolean; content: string }>('/api/content/generate-chapter', data),
  generateChapterContentStream: (data: ChapterContentRequest) => postJson('/api/content/generate-chapter-stream', data),
};

export const expandApi = {
  uploadExpandFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<FileUploadResponse>('/api/expand/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 300000,
    });
  },
};

export interface LocalDbFileUploadResponse {
  success: boolean;
  message: string;
  file_path?: string;
  ocr_applied?: boolean;
  ocr_char_count?: number;
}

export interface LocalDbFileInfo {
  name: string;
  size_bytes: number;
  mtime: string;
}

export interface LocalDbFileListResponse {
  success: boolean;
  message: string;
  files: LocalDbFileInfo[];
}

export interface LocalDbFileActionResponse {
  success: boolean;
  message: string;
}

export interface LocalDbRebuildFileResult {
  name: string;
  source_kind: string;
  success: boolean;
  char_count?: number;
  ocr_applied?: boolean;
  error?: string | null;
}

export interface LocalDbRebuildResponse {
  success: boolean;
  message: string;
  processed?: number;
  failed?: number;
  skipped?: number;
  ocr_files?: number;
  total_chars?: number;
  cleared_chunks?: number;
  file_results?: LocalDbRebuildFileResult[];
}

export const localDbApi = {
  uploadFile: (companyId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<LocalDbFileUploadResponse>('/api/localdb/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { company_id: companyId },
      timeout: 600000,
    });
  },

  listFiles: (companyId: string) =>
    api.get<LocalDbFileListResponse>('/api/localdb/files/list', {
      params: { company_id: companyId },
    }),

  deleteFile: (companyId: string, name: string) =>
    api.delete<LocalDbFileActionResponse>('/api/localdb/files/delete', {
      params: { name, company_id: companyId },
    }),

  downloadFile: (companyId: string, name: string) =>
    api.get<Blob>('/api/localdb/files/download', {
      params: { name, company_id: companyId },
      responseType: 'blob',
    }),

  rebuildKnowledge: (companyId: string) =>
    api.post<LocalDbRebuildResponse>('/api/localdb/knowledge/rebuild', null, {
      params: { company_id: companyId },
      timeout: 3600000,
    }),

  getExportTemplateInfo: (companyId: string) =>
    api.get<LocalDbTemplateInfoResponse>('/api/localdb/template/info', {
      params: { company_id: companyId },
    }),

  uploadExportTemplate: (companyId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<LocalDbFileUploadResponse>('/api/localdb/template/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { company_id: companyId },
      timeout: 120000,
    });
  },

  deleteExportTemplate: (companyId: string) =>
    api.delete<LocalDbFileActionResponse>('/api/localdb/template/delete', {
      params: { company_id: companyId },
    }),

  downloadExportTemplate: (companyId: string) =>
    api.get<Blob>('/api/localdb/template/download', {
      params: { company_id: companyId },
      responseType: 'blob',
    }),

  uploadCompanyInfoFile: (companyId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<LocalDbFileUploadResponse>('/api/localdb/company/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { company_id: companyId },
      timeout: 600000,
    });
  },

  listCompanyInfoFiles: (companyId: string) =>
    api.get<LocalDbFileListResponse>('/api/localdb/company/list', {
      params: { company_id: companyId },
    }),

  deleteCompanyInfoFile: (companyId: string, name: string) =>
    api.delete<LocalDbFileActionResponse>('/api/localdb/company/delete', {
      params: { name, company_id: companyId },
    }),

  downloadCompanyInfoFile: (companyId: string, name: string) =>
    api.get<Blob>('/api/localdb/company/download', {
      params: { name, company_id: companyId },
      responseType: 'blob',
    }),

  listAppendixTemplates: (companyId: string) =>
    api.get<LocalDbFileListResponse>('/api/localdb/appendix/list', {
      params: { company_id: companyId },
    }),

  uploadAppendixTemplate: (companyId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<LocalDbFileUploadResponse>('/api/localdb/appendix/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: { company_id: companyId },
    });
  },

  downloadFilledAppendixZip: (companyId: string, projectName?: string) =>
    api.get<Blob>('/api/localdb/appendix/download-filled-zip', {
      params: { company_id: companyId, project_name: projectName || '' },
      responseType: 'blob',
    }),

  saveCompanyBasicInfo: (
    companyId: string,
    payload: {
      company_name: string;
      unified_code: string;
      established_date: string;
      legal_representative: string;
      registered_capital: string;
      address: string;
      enterprise_scale: string;
      business_nature: string;
    }
  ) =>
    api.post<{ success: boolean; message: string; mtime?: string }>(
      '/api/localdb/company/save',
      payload,
      { params: { company_id: companyId } }
    ),
};

export default api;
