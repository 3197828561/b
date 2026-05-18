import React from 'react';
import { localDbApi, LocalDbFileInfo } from '../services/api';
import { saveAs } from 'file-saver';

const ACCEPTED_DOCS = '.pdf,.doc,.docx,.wps,.wpt,.rtf,.odt,.txt,.md';
const TEMPLATE_ACCEPT = '.docx';

interface LocalDbFilesProps {
  companyId: string;
}

/**
 * 公司本地数据库 - 资料文件（统一上传与搜索，不区分招标/投标）。
 */
const LocalDbFiles: React.FC<LocalDbFilesProps> = ({ companyId }) => {
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [message, setMessage] = React.useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );

  const [files, setFiles] = React.useState<LocalDbFileInfo[]>([]);
  const [downloadingName, setDownloadingName] = React.useState<string | null>(null);
  const [deletingName, setDeletingName] = React.useState<string | null>(null);

  const [searchKeyword, setSearchKeyword] = React.useState('');
  const [sortMode, setSortMode] = React.useState<'mtime' | 'size'>('mtime');
  const [rebuilding, setRebuilding] = React.useState(false);

  const [templateFile, setTemplateFile] = React.useState<File | null>(null);
  const [templateUploading, setTemplateUploading] = React.useState(false);
  const [templateExists, setTemplateExists] = React.useState(false);
  const [templateMtime, setTemplateMtime] = React.useState<string | null>(null);

  const refreshTemplateInfo = React.useCallback(async () => {
    try {
      const res = await localDbApi.getExportTemplateInfo(companyId);
      if (res.data?.success) {
        setTemplateExists(!!res.data.exists);
        setTemplateMtime(res.data.mtime || null);
      }
    } catch {
      setTemplateExists(false);
    }
  }, [companyId]);

  React.useEffect(() => {
    void refreshTemplateInfo();
  }, [refreshTemplateInfo]);

  const parseMtime = (mtime: string): number => {
    const normalized = mtime.replace(' ', 'T');
    const t = new Date(normalized).getTime();
    return Number.isNaN(t) ? 0 : t;
  };

  const viewFiles = React.useMemo(() => {
    const kw = searchKeyword.trim().toLowerCase();
    let filtered = kw ? files.filter((f) => f.name.toLowerCase().includes(kw)) : files;

    if (sortMode === 'size') {
      filtered = [...filtered].sort((a, b) => b.size_bytes - a.size_bytes);
    } else {
      filtered = [...filtered].sort((a, b) => parseMtime(b.mtime) - parseMtime(a.mtime));
    }
    return filtered;
  }, [files, searchKeyword, sortMode]);

  const refreshList = React.useCallback(async () => {
    try {
      const res = await localDbApi.listFiles(companyId);
      if (res.data?.success) {
        setFiles(res.data.files || []);
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      setMessage({ type: 'error', text: err?.message || '获取文件列表失败' });
    }
  }, [companyId]);

  React.useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const formatBytes = (bytes: number) => {
    if (!bytes && bytes !== 0) return '-';
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
  };

  const submitUpload = async () => {
    if (!selectedFile) {
      setMessage({ type: 'error', text: '请先选择文件' });
      return;
    }
    try {
      setUploading(true);
      setMessage(null);
      const res = await localDbApi.uploadFile(companyId, selectedFile);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '上传成功' });
        setSelectedFile(null);
        await refreshList();
      } else {
        setMessage({ type: 'error', text: res.data?.message || '上传失败' });
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      setMessage({ type: 'error', text: err?.message || '上传失败' });
    } finally {
      setUploading(false);
    }
  };

  const submitTemplateUpload = async () => {
    if (!templateFile) {
      setMessage({ type: 'error', text: '请先选择 Word 模板文件' });
      return;
    }
    try {
      setTemplateUploading(true);
      setMessage(null);
      const res = await localDbApi.uploadExportTemplate(companyId, templateFile);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '模板已保存' });
        setTemplateFile(null);
        await refreshTemplateInfo();
      } else {
        setMessage({ type: 'error', text: res.data?.message || '模板上传失败' });
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      setMessage({ type: 'error', text: err?.message || '模板上传失败' });
    } finally {
      setTemplateUploading(false);
    }
  };

  const handleRebuildKnowledge = async () => {
    const ok = window.confirm(
      '将重新从磁盘读取全部资料文件，抽取文本并执行 OCR，写入知识库。\n\n' +
        '公司基本信息不会改动。文件较多时可能需较长时间。是否继续？'
    );
    if (!ok) return;

    try {
      setRebuilding(true);
      setMessage(null);
      const res = await localDbApi.rebuildKnowledge(companyId);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '知识库重建完成' });
      } else {
        setMessage({ type: 'error', text: res.data?.message || '知识库重建失败' });
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      setMessage({
        type: 'error',
        text: err?.message || '知识库重建失败（请耐心等待或查看后端日志）',
      });
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-2">数据库文件</h2>
        <p className="text-sm text-gray-600">
          当前公司库 ID：<span className="font-mono text-gray-800">{companyId}</span>
          。支持 PDF、Word（.doc/.docx）、WPS（.wps）、RTF、ODT、TXT 等；旧版格式可自动转换（需本机 Word 或 LibreOffice）。
        </p>
        <p className="mt-2 text-xs text-gray-500">
          Word 内嵌图片会导出到本地库并 OCR 进检索文本；扫描件也会自动 OCR。下载原文件可查看完整版式。
        </p>

        <label className="mt-6 block w-full border-2 border-dashed border-gray-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-400 transition-colors">
          <input
            type="file"
            accept={ACCEPTED_DOCS}
            className="hidden"
            onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
          />
          <div className="text-sm text-gray-600">
            {selectedFile ? `已选择：${selectedFile.name}` : '点击选择文件（PDF / Word / WPS / RTF / TXT 等）'}
          </div>
          <div className="mt-2 text-xs text-gray-500">支持 .pdf / .doc / .docx</div>
        </label>

        <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
          <button
            type="button"
            onClick={() => void handleRebuildKnowledge()}
            disabled={rebuilding || files.length === 0}
            className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {rebuilding ? '重建中…' : '重建知识库'}
          </button>
          <button
            type="button"
            onClick={() => void submitUpload()}
            disabled={uploading || !selectedFile}
            className="inline-flex items-center px-5 py-2 text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            {uploading ? '上传中…' : '上传文件'}
          </button>
        </div>

        {message && (
          <div
            className={`mt-4 p-3 rounded-md text-sm ${
              message.type === 'success'
                ? 'bg-green-100 text-green-700 border border-green-200'
                : 'bg-red-100 text-red-700 border border-red-200'
            }`}
          >
            {message.text}
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">投标 Word 导出模板</h2>
        <p className="text-sm text-gray-600 mb-2">
          上传公司固定版式（封面、页眉页脚、样式等）。导出 Word 时保留模板内容，其后接入生成的章节正文。
        </p>
        {templateExists ? (
          <p className="text-xs text-green-700 mb-4">
            当前已配置模板{templateMtime ? `（更新于 ${templateMtime}）` : ''}
          </p>
        ) : (
          <p className="text-xs text-gray-500 mb-4">未上传模板时，导出使用系统默认宋体版式。</p>
        )}
        <label className="block w-full border-2 border-dashed border-indigo-200 rounded-lg p-5 text-center cursor-pointer hover:border-indigo-400 bg-indigo-50/30">
          <input
            type="file"
            accept={TEMPLATE_ACCEPT}
            className="hidden"
            onChange={(e) => setTemplateFile(e.target.files?.[0] || null)}
          />
          <div className="text-sm text-gray-600">
            {templateFile ? `已选择：${templateFile.name}` : '点击选择 .docx 模板'}
          </div>
        </label>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          {templateExists && (
            <>
              <button
                type="button"
                onClick={async () => {
                  try {
                    const resp = await localDbApi.downloadExportTemplate(companyId);
                    saveAs(resp.data, '投标导出模板.docx');
                  } catch (e: unknown) {
                    const err = e as { message?: string };
                    setMessage({ type: 'error', text: err?.message || '下载失败' });
                  }
                }}
                className="px-3 py-2 text-sm border border-gray-300 rounded-md"
              >
                下载模板
              </button>
              <button
                type="button"
                onClick={async () => {
                  if (!window.confirm('确认删除当前导出模板？')) return;
                  const res = await localDbApi.deleteExportTemplate(companyId);
                  if (res.data?.success) {
                    setMessage({ type: 'success', text: '已删除导出模板' });
                    await refreshTemplateInfo();
                  } else {
                    setMessage({ type: 'error', text: res.data?.message || '删除失败' });
                  }
                }}
                className="px-3 py-2 text-sm border border-red-300 rounded-md text-red-700 bg-red-50"
              >
                删除模板
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => void submitTemplateUpload()}
            disabled={templateUploading || !templateFile}
            className="px-4 py-2 text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400"
          >
            {templateUploading ? '上传中…' : templateExists ? '替换模板' : '上传模板'}
          </button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex flex-col sm:flex-row sm:items-end gap-4 mb-4">
          <div className="flex-1">
            <label htmlFor="localdb-search" className="block text-sm font-medium text-gray-700 mb-2">
              搜索文件
            </label>
            <input
              id="localdb-search"
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              placeholder="输入文件名关键字"
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="localdb-sort" className="block text-sm font-medium text-gray-700 mb-2">
              排序
            </label>
            <select
              id="localdb-sort"
              value={sortMode}
              onChange={(e) => setSortMode(e.target.value as 'mtime' | 'size')}
              className="px-3 pr-10 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="mtime">按时间</option>
              <option value="size">按大小</option>
            </select>
          </div>
          <button
            type="button"
            onClick={() => void refreshList()}
            className="text-sm text-blue-600 hover:text-blue-700 sm:mb-0.5"
          >
            刷新列表
          </button>
        </div>

        {viewFiles.length === 0 ? (
          <div className="border border-gray-200 rounded-md p-6 text-sm text-gray-500 text-center">
            {searchKeyword.trim() ? '没有匹配的文件' : '暂无已上传文件'}
          </div>
        ) : (
          <ul className="space-y-3">
            {viewFiles.map((f) => (
              <li
                key={f.name}
                className="flex items-start justify-between gap-3 border border-gray-200 rounded-md p-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-900 truncate">{f.name}</div>
                  <div className="text-xs text-gray-500 mt-1">
                    {f.mtime} / {formatBytes(f.size_bytes)}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        setDownloadingName(f.name);
                        const resp = await localDbApi.downloadFile(companyId, f.name);
                        saveAs(resp.data, f.name);
                      } catch (e: unknown) {
                        const err = e as { message?: string };
                        setMessage({ type: 'error', text: err?.message || '下载失败' });
                      } finally {
                        setDownloadingName(null);
                      }
                    }}
                    disabled={downloadingName === f.name}
                    className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                  >
                    下载
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (!window.confirm(`确认删除：${f.name} 吗？`)) return;
                      try {
                        setDeletingName(f.name);
                        const res = await localDbApi.deleteFile(companyId, f.name);
                        if (res.data?.success) {
                          setMessage({ type: 'success', text: '删除成功' });
                          await refreshList();
                        } else {
                          setMessage({ type: 'error', text: res.data?.message || '删除失败' });
                        }
                      } catch (e: unknown) {
                        const err = e as { message?: string };
                        setMessage({ type: 'error', text: err?.message || '删除失败' });
                      } finally {
                        setDeletingName(null);
                      }
                    }}
                    disabled={deletingName === f.name}
                    className="px-3 py-1.5 text-sm border border-red-300 rounded-md text-red-700 bg-red-50 hover:bg-red-100 disabled:opacity-50"
                  >
                    删除
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default LocalDbFiles;
