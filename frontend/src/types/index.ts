/**
 * 类型定义
 */

/** 左侧可选公司：id 传给后端作 localdb 隔离，name 为展示名 */
export interface CompanyProfile {
  id: string;
  name: string;
}

export interface OutlineItem {
  id: string;
  title: string;
  description: string;
  source_requirement_id?: string;
  source_requirement_title?: string;
  children?: OutlineItem[];
  content?: string;
}

export type OutlineMode = 'free' | 'aligned';

export interface OutlineData {
  outline: OutlineItem[];
  project_name?: string;
  project_overview?: string;
}

/** 技术评分大类（与后端 TechnicalRequirementGroup 一致） */
export interface TechnicalRequirementGroup {
  requirement_id: string;
  title: string;
  description: string;
  detail_points?: string[];
}

export interface AppState {
  /**
   * UI 模式：当前展示的是步骤流程页还是“公司本地数据库”页
   */
  uiMode: 'steps' | 'localDb';
  /**
   * 在 localDb 模式下的子页面
   */
  localDbView: 'dbFiles' | 'companyBasicInfo' | 'appendix';
  currentStep: number;
  fileContent: string;
  projectOverview: string;
  techRequirements: string;
  outlineData: OutlineData | null;
  /** 全书正文（全部末级章节合计）目标总字数下限，单位：字（字符计） */
  bookWordCountMin: number;
  /** 全书正文目标总字数上限 */
  bookWordCountMax: number;
  /** 可选公司列表；id 与后端 uploads/localdb 下目录对应 */
  companies: CompanyProfile[];
  /** 当前选中的公司 id，本地数据库与生成正文检索均用此 id */
  activeCompanyId: string;
  /** 从招标评分要求提取的评分项，用于目录覆盖检查 */
  scoringItems: TechnicalRequirementGroup[];
}
