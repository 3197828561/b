import React from 'react';
import { localDbApi, LocalDbFileInfo } from '../services/api';
import { saveAs } from 'file-saver';

const ACCEPTED_DOCS = '.pdf,.doc,.docx';

/**
 * 公司本地数据库 - 数据库文件页（当前仅做界面占位/切换）。
 */
const LocalDbFiles: React.FC = () => {
  const [tenderFile, setTenderFile] = React.useState<File | null>(null);
  const [bidFile, setBidFile] = React.useState<File | null>(null);

  const [tenderUploading, setTenderUploading] = React.useState(false);
  const [bidUploading, setBidUploading] = React.useState(false);

  const [message, setMessage] = React.useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [tenderFiles, setTenderFiles] = React.useState<LocalDbFileInfo[]>([]);
  const [bidFiles, setBidFiles] = React.useState<LocalDbFileInfo[]>([]);

  const [downloadingName, setDownloadingName] = React.useState<string | null>(null);
  const [deletingName, setDeletingName] = React.useState<string | null>(null);

  const [searchKeyword, setSearchKeyword] = React.useState<string>('');
  const [sortMode, setSortMode] = React.useState<'mtime' | 'size'>('mtime');

  const parseMtime = (mtime: string): number => {
    // mtime: "YYYY-MM-DD HH:mm:ss"
    const normalized = mtime.replace(' ', 'T');
    const t = new Date(normalized).getTime();
    return Number.isNaN(t) ? 0 : t;
  };

  const filterAndSort = (files: LocalDbFileInfo[]) => {
    const kw = searchKeyword.trim().toLowerCase();
    let filtered = kw
      ? files.filter((f) => f.name.toLowerCase().includes(kw))
      : files;

    if (sortMode === 'size') {
      filtered = [...filtered].sort((a, b) => b.size_bytes - a.size_bytes);
    } else {
      filtered = [...filtered].sort(
        (a, b) => parseMtime(b.mtime) - parseMtime(a.mtime)
      );
    }

    return filtered;
  };

  const tenderViewFiles = filterAndSort(tenderFiles);
  const bidViewFiles = filterAndSort(bidFiles);

  const refreshLists = React.useCallback(async () => {
    try {
      const [tenderRes, bidRes] = await Promise.all([
        localDbApi.listTenderFiles(),
        localDbApi.listBidFiles(),
      ]);

      if (tenderRes.data?.success) setTenderFiles(tenderRes.data.files || []);
      if (bidRes.data?.success) setBidFiles(bidRes.data.files || []);
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || '获取文件列表失败' });
    }
  }, []);

  React.useEffect(() => {
    void refreshLists();
  }, [refreshLists]);

  const formatBytes = (bytes: number) => {
    if (!bytes && bytes !== 0) return '-';
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    const mb = kb / 1024;
    return `${mb.toFixed(1)} MB`;
  };

  const submitTender = async () => {
    if (!tenderFile) {
      setMessage({ type: 'error', text: '请先选择招标文件' });
      return;
    }

    try {
      setTenderUploading(true);
      setMessage(null);
      const res = await localDbApi.uploadTenderFile(tenderFile);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '招标文件提交成功' });
        setTenderFile(null);
        await refreshLists();
      } else {
        setMessage({ type: 'error', text: res.data?.message || '招标文件提交失败' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || '招标文件提交失败' });
    } finally {
      setTenderUploading(false);
    }
  };

  const submitBid = async () => {
    if (!bidFile) {
      setMessage({ type: 'error', text: '请先选择投标文件' });
      return;
    }

    try {
      setBidUploading(true);
      setMessage(null);
      const res = await localDbApi.uploadBidFile(bidFile);
      if (res.data?.success) {
        setMessage({ type: 'success', text: res.data.message || '投标文件提交成功' });
        setBidFile(null);
        await refreshLists();
      } else {
        setMessage({ type: 'error', text: res.data?.message || '投标文件提交失败' });
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: e?.message || '投标文件提交失败' });
    } finally {
      setBidUploading(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-2">数据库文件</h2>
        <p className="text-sm text-gray-600">可提交招标文件与投标文件（Word/PDF），并保存到公司本地数据库目录。</p>

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 招标文件 */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">招标文件</h3>

          <label
            className="block w-full border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-gray-400 transition-colors"
          >
            <input
              type="file"
              accept={ACCEPTED_DOCS}
              className="hidden"
              onChange={(e) => setTenderFile(e.target.files?.[0] || null)}
            />
            <div className="text-sm text-gray-600">
              {tenderFile ? `已选择：${tenderFile.name}` : `点击选择招标文件（Word/PDF）`}
            </div>
            <div className="mt-2 text-xs text-gray-500">支持：.pdf / .doc / .docx</div>
          </label>

          <div className="mt-4 flex justify-end">
            <button
              onClick={submitTender}
              disabled={tenderUploading}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {tenderUploading ? '提交中...' : '提交招标文件'}
            </button>
          </div>
        </div>

        {/* 投标文件 */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">投标文件</h3>

          <label
            className="block w-full border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-gray-400 transition-colors"
          >
            <input
              type="file"
              accept={ACCEPTED_DOCS}
              className="hidden"
              onChange={(e) => setBidFile(e.target.files?.[0] || null)}
            />
            <div className="text-sm text-gray-600">
              {bidFile ? `已选择：${bidFile.name}` : `点击选择投标文件（Word/PDF）`}
            </div>
            <div className="mt-2 text-xs text-gray-500">支持：.pdf / .doc / .docx</div>
          </label>

          <div className="mt-4 flex justify-end">
            <button
              onClick={submitBid}
              disabled={bidUploading}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
            >
              {bidUploading ? '提交中...' : '提交投标文件'}
            </button>
          </div>
        </div>
      </div>

      {/* 搜索 + 排序 */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
          <div className="flex-1">
            <label htmlFor="localdb-search" className="block text-sm font-medium text-gray-700 mb-2">
              搜索关键字
            </label>
            <input
              id="localdb-search"
              value={searchKeyword}
              onChange={(e) => setSearchKeyword(e.target.value)}
              placeholder="输入文件名关键字，例如：招标 / 投标"
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label htmlFor="localdb-sort" className="block text-sm font-medium text-gray-700 mb-2">
              排序方式
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
        </div>
      </div>

      {/* 列表区：可保存/删除 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 招标文件列表 */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between gap-4 mb-4">
            <h3 className="text-lg font-semibold text-gray-900">已提交的招标文件</h3>
            <button
              onClick={() => void refreshLists()}
              className="text-sm text-blue-600 hover:text-blue-700"
            >
              刷新
            </button>
          </div>

          {tenderViewFiles.length === 0 ? (
            <div className="border border-gray-200 rounded-md p-4 text-sm text-gray-500">
              暂无文件
            </div>
          ) : (
            <div className="space-y-3">
              {tenderViewFiles.map((f) => (
                <div
                  key={f.name}
                  className="flex items-start justify-between gap-3 border border-gray-200 rounded-md p-3"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">
                      {f.name}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {f.mtime} / {formatBytes(f.size_bytes)}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={async () => {
                        try {
                          setDownloadingName(f.name);
                          const resp = await localDbApi.downloadTenderFile(f.name);
                          saveAs(resp.data, f.name);
                        } catch (e: any) {
                          setMessage({ type: 'error', text: e?.message || '保存失败' });
                        } finally {
                          setDownloadingName(null);
                        }
                      }}
                      disabled={downloadingName === f.name}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                    >
                      保存
                    </button>
                    <button
                      onClick={async () => {
                        if (!window.confirm(`确认删除：${f.name} 吗？`)) return;
                        try {
                          setDeletingName(f.name);
                          const res = await localDbApi.deleteTenderFile(f.name);
                          if (!res.data?.success) {
                            setMessage({ type: 'error', text: res.data?.message || '删除失败' });
                            return;
                          }
                          setMessage({ type: 'success', text: '删除成功' });
                          await refreshLists();
                        } catch (e: any) {
                          setMessage({ type: 'error', text: e?.message || '删除失败' });
                        } finally {
                          setDeletingName(null);
                        }
                      }}
                      disabled={deletingName === f.name}
                      className="inline-flex items-center px-3 py-1.5 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-red-50 hover:bg-red-100 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 投标文件列表 */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between gap-4 mb-4">
            <h3 className="text-lg font-semibold text-gray-900">已提交的投标文件</h3>
            <button
              onClick={() => void refreshLists()}
              className="text-sm text-blue-600 hover:text-blue-700"
            >
              刷新
            </button>
          </div>

          {bidViewFiles.length === 0 ? (
            <div className="border border-gray-200 rounded-md p-4 text-sm text-gray-500">
              暂无文件
            </div>
          ) : (
            <div className="space-y-3">
              {bidViewFiles.map((f) => (
                <div
                  key={f.name}
                  className="flex items-start justify-between gap-3 border border-gray-200 rounded-md p-3"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">
                      {f.name}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      {f.mtime} / {formatBytes(f.size_bytes)}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={async () => {
                        try {
                          setDownloadingName(f.name);
                          const resp = await localDbApi.downloadBidFile(f.name);
                          saveAs(resp.data, f.name);
                        } catch (e: any) {
                          setMessage({ type: 'error', text: e?.message || '保存失败' });
                        } finally {
                          setDownloadingName(null);
                        }
                      }}
                      disabled={downloadingName === f.name}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                    >
                      保存
                    </button>
                    <button
                      onClick={async () => {
                        if (!window.confirm(`确认删除：${f.name} 吗？`)) return;
                        try {
                          setDeletingName(f.name);
                          const res = await localDbApi.deleteBidFile(f.name);
                          if (!res.data?.success) {
                            setMessage({ type: 'error', text: res.data?.message || '删除失败' });
                            return;
                          }
                          setMessage({ type: 'success', text: '删除成功' });
                          await refreshLists();
                        } catch (e: any) {
                          setMessage({ type: 'error', text: e?.message || '删除失败' });
                        } finally {
                          setDeletingName(null);
                        }
                      }}
                      disabled={deletingName === f.name}
                      className="inline-flex items-center px-3 py-1.5 border border-red-300 text-sm font-medium rounded-md text-red-700 bg-red-50 hover:bg-red-100 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default LocalDbFiles;

