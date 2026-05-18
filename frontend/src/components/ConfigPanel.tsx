/**
 * 左侧栏：公司切换、名称维护、本地数据库入口
 */
import React, { useEffect, useState } from 'react';
import {
  BuildingOffice2Icon,
  CircleStackIcon,
  PlusCircleIcon,
} from '@heroicons/react/24/outline';
import type { CompanyProfile } from '../types';

interface ConfigPanelProps {
  companies: CompanyProfile[];
  activeCompanyId: string;
  onSelectCompany: (id: string) => void;
  onAddCompany: (name: string) => void;
  onRenameCompany: (id: string, name: string) => void;
  onRemoveCompany: (id: string) => void;
  onOpenLocalDb: () => void;
}

const inputClass =
  'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20';

const ConfigPanel: React.FC<ConfigPanelProps> = ({
  companies,
  activeCompanyId,
  onSelectCompany,
  onAddCompany,
  onRenameCompany,
  onRemoveCompany,
  onOpenLocalDb,
}) => {
  const [newName, setNewName] = useState('');
  const [renameModalOpen, setRenameModalOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState('');

  const active = companies.find((c) => c.id === activeCompanyId);

  useEffect(() => {
    if (!renameModalOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setRenameModalOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [renameModalOpen]);

  const handleAdd = () => {
    const t = newName.trim();
    if (!t) return;
    onAddCompany(t);
    setNewName('');
  };

  const openRenameModal = () => {
    setRenameDraft((active?.name ?? '').replace(/\r?\n/g, ''));
    setRenameModalOpen(true);
  };

  const handleSaveRename = () => {
    const t = renameDraft.trim();
    if (!t || !activeCompanyId) return;
    onRenameCompany(activeCompanyId, t);
    setRenameModalOpen(false);
  };

  const handleRemove = () => {
    if (activeCompanyId === 'default') return;
    if (companies.length <= 1) return;
    if (
      !window.confirm(
        `确定删除公司「${active?.name ?? ''}」吗？仅删除列表项，已上传的磁盘数据仍保留在服务器对应目录中。`
      )
    ) {
      return;
    }
    onRemoveCompany(activeCompanyId);
  };

  const canDelete = activeCompanyId !== 'default' && companies.length > 1;

  return (
    <div className="flex h-full min-h-0 w-80 flex-col border-r border-gray-200/80 bg-gradient-to-b from-slate-50 via-white to-slate-50/80 shadow-[2px_0_12px_-4px_rgba(15,23,42,0.08)]">
      {/* 顶栏 */}
      <header className="shrink-0 border-b border-gray-100/90 bg-white/80 px-5 py-5 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-600/25">
            <BuildingOffice2Icon className="h-5 w-5" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-blue-600/90">工作台</p>
            <p className="break-words text-sm font-semibold leading-snug text-gray-900">公司与资料库</p>
          </div>
        </div>
      </header>

      {/* 可滚动主体 */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {/* 当前公司 */}
        <section className="rounded-xl border border-gray-100 bg-white/90 p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2 text-gray-800">
            <BuildingOffice2Icon className="h-4 w-4 text-gray-400" aria-hidden />
            <h2 className="text-sm font-semibold">当前公司</h2>
          </div>
          <p id="company-list-label" className="sr-only">
            选择公司
          </p>
          <ul
            role="listbox"
            aria-labelledby="company-list-label"
            className="max-h-52 space-y-1.5 overflow-y-auto pr-0.5"
          >
            {companies.map((c) => {
              const selected = c.id === activeCompanyId;
              return (
                <li key={c.id} role="option" aria-selected={selected}>
                  <button
                    type="button"
                    onClick={() => onSelectCompany(c.id)}
                    className={`w-full rounded-lg px-3 py-2.5 text-left text-sm font-medium leading-snug transition focus:outline-none focus:ring-2 focus:ring-blue-500/40 ${
                      selected
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'bg-slate-50 text-gray-900 hover:bg-slate-100'
                    }`}
                  >
                    <span className="block break-words">{c.name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {active && (
            <div className="mt-3 flex gap-2 border-t border-gray-100 pt-3">
              <button
                type="button"
                onClick={openRenameModal}
                className="inline-flex flex-1 items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500/25"
              >
                修改名称
              </button>
              <button
                type="button"
                onClick={handleRemove}
                disabled={!canDelete}
                title={
                  activeCompanyId === 'default'
                    ? '默认公司不可删除'
                    : companies.length <= 1
                      ? '至少保留一家公司'
                      : '从列表移除（不删服务器文件）'
                }
                className="inline-flex flex-1 items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm transition hover:border-gray-300 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500/25 disabled:cursor-not-allowed disabled:opacity-40"
              >
                删除
              </button>
            </div>
          )}
        </section>

        {/* 添加公司 */}
        <section className="rounded-xl border border-dashed border-gray-200 bg-slate-50/50 p-4">
          <div className="mb-3 flex items-center gap-2 text-gray-800">
            <PlusCircleIcon className="h-4 w-4 text-gray-400" aria-hidden />
            <h2 className="text-sm font-semibold">添加新公司</h2>
          </div>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="输入公司全称"
            className={inputClass}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAdd();
              }
            }}
          />
          <button
            type="button"
            onClick={handleAdd}
            className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm font-medium text-gray-800 shadow-sm transition hover:border-gray-300 hover:bg-gray-50"
          >
            <PlusCircleIcon className="h-4 w-4 text-gray-500" aria-hidden />
            添加并切换
          </button>
        </section>
      </div>

      {/* 底部主操作 */}
      <footer className="shrink-0 border-t border-gray-100 bg-white/90 p-5 backdrop-blur-sm">
        <button
          type="button"
          onClick={onOpenLocalDb}
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/25 transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          <CircleStackIcon className="h-5 w-5 opacity-95" aria-hidden />
          公司本地数据库
        </button>
        <p className="mt-2 text-center text-[10px] text-gray-400">资料文件 · 公司基本信息</p>
      </footer>

      {renameModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="rename-company-title"
        >
          <button
            type="button"
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px]"
            aria-label="关闭"
            onClick={() => setRenameModalOpen(false)}
          />
          <div className="relative w-full max-w-md rounded-xl border border-gray-200 bg-white p-5 shadow-xl">
            <h3 id="rename-company-title" className="text-base font-semibold text-gray-900">
              修改公司名称
            </h3>
            <p className="mt-1 text-xs text-gray-500">保存后在列表与各页面中显示为新名称。</p>
            <textarea
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value.replace(/\r?\n/g, ''))}
              rows={3}
              autoFocus
              className={`${inputClass} mt-4 min-h-[5rem] resize-y leading-snug`}
              placeholder="输入公司显示名称"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRenameModalOpen(false)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-gray-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSaveRename}
                disabled={!renameDraft.trim()}
                className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-45"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ConfigPanel;
