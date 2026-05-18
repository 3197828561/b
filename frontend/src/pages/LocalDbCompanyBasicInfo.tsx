import React from 'react';
import { localDbApi } from '../services/api';

interface LocalDbCompanyBasicInfoProps {
  companyId: string;
  /** 左侧当前选中公司的展示名，用于切换公司时预填「公司」字段 */
  displayCompanyName: string;
}

const DEFAULT_DEMO = {
  companyName: '昆山市尚为人力资源配置服务有限公司',
  unifiedCode: '91320583742479647J',
  establishedDate: '2002 年 8 月 23 日',
  legalRepresentative: '张淇',
  registeredCapital: '200 万元',
  address: '昆山市玉山镇长江南路 666 号利得国际商务楼 1101 室',
  enterpriseScale:
    '职工 121 人，其中中高级职称 15 人；资产总计 1500 万元，净资产 600 万元',
  businessNature:
    '有限责任公司（自然人投资 / 控股），具备劳务派遣、人力资源服务双资质',
};

/**
 * 公司本地数据库 - 公司基本信息页（按 companyId 写入对应知识库）。
 */
const LocalDbCompanyBasicInfo: React.FC<LocalDbCompanyBasicInfoProps> = ({
  companyId,
  displayCompanyName,
}) => {
  const [companyName, setCompanyName] = React.useState(DEFAULT_DEMO.companyName);
  const [unifiedCode, setUnifiedCode] = React.useState(DEFAULT_DEMO.unifiedCode);
  const [establishedDate, setEstablishedDate] = React.useState(DEFAULT_DEMO.establishedDate);
  const [legalRepresentative, setLegalRepresentative] = React.useState(
    DEFAULT_DEMO.legalRepresentative
  );
  const [registeredCapital, setRegisteredCapital] = React.useState(DEFAULT_DEMO.registeredCapital);
  const [address, setAddress] = React.useState(DEFAULT_DEMO.address);
  const [enterpriseScale, setEnterpriseScale] = React.useState(DEFAULT_DEMO.enterpriseScale);
  const [businessNature, setBusinessNature] = React.useState(DEFAULT_DEMO.businessNature);
  const [isEditing, setIsEditing] = React.useState(false);
  const [message, setMessage] = React.useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  );

  React.useEffect(() => {
    setIsEditing(false);
    setMessage(null);
    if (companyId === 'default') {
      setCompanyName(displayCompanyName || DEFAULT_DEMO.companyName);
      setUnifiedCode(DEFAULT_DEMO.unifiedCode);
      setEstablishedDate(DEFAULT_DEMO.establishedDate);
      setLegalRepresentative(DEFAULT_DEMO.legalRepresentative);
      setRegisteredCapital(DEFAULT_DEMO.registeredCapital);
      setAddress(DEFAULT_DEMO.address);
      setEnterpriseScale(DEFAULT_DEMO.enterpriseScale);
      setBusinessNature(DEFAULT_DEMO.businessNature);
    } else {
      setCompanyName(displayCompanyName || '');
      setUnifiedCode('');
      setEstablishedDate('');
      setLegalRepresentative('');
      setRegisteredCapital('');
      setAddress('');
      setEnterpriseScale('');
      setBusinessNature('');
    }
  }, [companyId, displayCompanyName]);

  const handleEdit = () => {
    setIsEditing(true);
    setMessage(null);
  };

  const handleConfirm = () => {
    void (async () => {
      try {
        const res = await localDbApi.saveCompanyBasicInfo(companyId, {
          company_name: companyName,
          unified_code: unifiedCode,
          established_date: establishedDate,
          legal_representative: legalRepresentative,
          registered_capital: registeredCapital,
          address,
          enterprise_scale: enterpriseScale,
          business_nature: businessNature,
        });

        if (res.data?.success) {
          setIsEditing(false);
          setMessage({ type: 'success', text: res.data.message || '公司基本信息已保存' });
          setTimeout(() => setMessage(null), 3000);
          return;
        }

        setMessage({ type: 'error', text: res.data?.message || '公司基本信息保存失败' });
      } catch (e: unknown) {
        const err = e as { message?: string };
        setMessage({ type: 'error', text: err?.message || '公司基本信息保存失败' });
      }
    })();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <p className="text-xs text-gray-500 mb-4">
          当前库：<span className="font-mono text-gray-800">{companyId}</span>
        </p>
        <div className="flex flex-col gap-2">
          <span className="text-xl font-semibold text-gray-900">公司</span>
          <textarea
            rows={3}
            className={`w-full min-h-[4.5rem] resize-y px-3 py-2 text-base leading-relaxed rounded-md border shadow-sm focus:outline-none focus:ring-2 break-words ${
              isEditing
                ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
            }`}
            value={companyName}
            disabled={!isEditing}
            onChange={(e) => setCompanyName(e.target.value.replace(/\r?\n/g, ''))}
          />
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

        <div className="mt-6 space-y-4">
          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>统一社会信用代码：</span>
            <input
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={unifiedCode}
              disabled={!isEditing}
              onChange={(e) => setUnifiedCode(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>成立时间：</span>
            <input
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={establishedDate}
              disabled={!isEditing}
              onChange={(e) => setEstablishedDate(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>法定代表人：</span>
            <input
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={legalRepresentative}
              disabled={!isEditing}
              onChange={(e) => setLegalRepresentative(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>注册资本：</span>
            <input
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={registeredCapital}
              disabled={!isEditing}
              onChange={(e) => setRegisteredCapital(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>注册 / 经营地址：</span>
            <textarea
              rows={3}
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 resize-y ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={address}
              disabled={!isEditing}
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>企业规模：</span>
            <textarea
              rows={3}
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 resize-y ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={enterpriseScale}
              disabled={!isEditing}
              onChange={(e) => setEnterpriseScale(e.target.value)}
            />
          </div>

          <div className="text-xl font-semibold text-gray-900 flex items-center flex-wrap gap-x-3 gap-y-2">
            <span>经营性质：</span>
            <textarea
              rows={3}
              className={`w-[420px] max-w-full px-3 py-2 text-base rounded-md border shadow-sm focus:outline-none focus:ring-2 resize-y ${
                isEditing
                  ? 'border-blue-400 focus:ring-blue-500 bg-white text-gray-900'
                  : 'border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed'
              }`}
              value={businessNature}
              disabled={!isEditing}
              onChange={(e) => setBusinessNature(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={handleEdit}
            disabled={isEditing}
            className="inline-flex items-center px-4 py-2 border border-blue-600 text-sm font-medium rounded-md text-blue-700 bg-blue-50 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            修改
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!isEditing}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
};

export default LocalDbCompanyBasicInfo;
