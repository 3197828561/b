import React from 'react';
import { saveAs } from 'file-saver';
import { localDbApi, getErrorMessage } from '../services/api';

interface LocalDbAppendixProps {
  companyId: string;
}

/**
 * 投标附录模板：上传 .docx（占位符 {{company_name}} 等）、下载填空 ZIP。
 */
const LocalDbAppendix: React.FC<LocalDbAppendixProps> = ({ companyId }) => {
  const [files, setFiles] = React.useState<{ name: string; mtime: string }[]>([]);
  const [selected, setSelected] = React.useState<File | null>(null);
  const [projectName, setProjectName] = React.useState('');
  const [message, setMessage] = React.useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );

  const loadList = React.useCallback(async () => {
    try {
      const res = await localDbApi.listAppendixTemplates(companyId);
      if (res.data?.success) {
        setFiles(res.data.files.map((f) => ({ name: f.name, mtime: f.mtime })));
      }
    } catch {
      setFiles([]);
    }
  }, [companyId]);

  React.useEffect(() => {
    void loadList();
  }, [loadList]);

  const handleUpload = async () => {
    if (!selected) {
      setMessage({ type: 'error', text: '请先选择 .docx 模板' });
      return;
    }
    try {
      const res = await localDbApi.uploadAppendixTemplate(companyId, selected);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '上传成功' });
        setSelected(null);
        await loadList();
      } else {
        setMessage({ type: 'error', text: res.data?.message || '上传失败' });
      }
    } catch (e) {
      setMessage({ type: 'error', text: getErrorMessage(e, '上传失败') });
    }
  };

  const handleDownloadZip = async () => {
    try {
      const resp = await localDbApi.downloadFilledAppendixZip(companyId, projectName);
      saveAs(resp.data, '投标附录.zip');
      setMessage({ type: 'success', text: '已下载填空附录 ZIP' });
    } catch (e) {
      setMessage({ type: 'error', text: getErrorMessage(e, '下载失败') });
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">投标附录模板</h2>
        <p className="text-sm text-gray-600 mb-4">
          模板内可使用占位符：
          <code className="mx-1 text-xs bg-gray-100 px-1 rounded">{'{{company_name}}'}</code>
          <code className="mx-1 text-xs bg-gray-100 px-1 rounded">{'{{legal_representative}}'}</code>
          <code className="mx-1 text-xs bg-gray-100 px-1 rounded">{'{{project_name}}'}</code>
          <code className="mx-1 text-xs bg-gray-100 px-1 rounded">{'{{date}}'}</code>
          等。请先在「公司基本信息」保存资料后再下载填空文件。
        </p>

        <div className="flex flex-wrap gap-3 items-end mb-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">项目名称（填入模板）</label>
            <input
              type="text"
              className="border rounded px-3 py-2 text-sm w-64"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="可选"
            />
          </div>
          <button
            type="button"
            onClick={() => void handleDownloadZip()}
            className="px-4 py-2 text-sm rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
          >
            下载填空附录 ZIP
          </button>
        </div>

        <div className="border border-dashed rounded-lg p-4 mb-4">
          <input
            type="file"
            accept=".docx"
            onChange={(e) => setSelected(e.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={() => void handleUpload()}
            className="mt-2 px-4 py-2 text-sm rounded-md border border-gray-300 hover:bg-gray-50"
          >
            上传/替换模板
          </button>
        </div>

        <ul className="text-sm text-gray-700 space-y-1">
          {files.length === 0 && <li className="text-gray-400">暂无模板（将自动创建默认三份）</li>}
          {files.map((f) => (
            <li key={f.name} className="flex justify-between border-b border-gray-100 py-1">
              <span>{f.name}</span>
              <span className="text-gray-400 text-xs">{f.mtime}</span>
            </li>
          ))}
        </ul>

        {message && (
          <p
            className={`mt-4 text-sm ${
              message.type === 'success' ? 'text-green-600' : 'text-red-600'
            }`}
          >
            {message.text}
          </p>
        )}
      </div>
    </div>
  );
};

export default LocalDbAppendix;
