/**
 * 应用状态管理Hook
 */
import { useState, useCallback } from 'react';
import { AppState, CompanyProfile, OutlineData, TechnicalRequirementGroup } from '../types';
import { draftStorage } from '../utils/draftStorage';

const DEFAULT_COMPANIES: CompanyProfile[] = [
  { id: 'default', name: '昆山市尚为人力资源配置服务有限公司' },
];

const initialState: AppState = {
  uiMode: 'steps',
  localDbView: 'dbFiles',
  currentStep: 0,
  fileContent: '',
  projectOverview: '',
  techRequirements: '',
  outlineData: null,
  bookWordCountMin: 30_000,
  bookWordCountMax: 50_000,
  companies: DEFAULT_COMPANIES,
  activeCompanyId: 'default',
  scoringItems: [],
};

export const useAppState = () => {
  const [state, setState] = useState<AppState>(() => {
    const draft = draftStorage.loadDraft() as (Partial<AppState> & Record<string, unknown>) | null;
    const merged: Record<string, unknown> = draft ? { ...draft } : {};
    delete merged.chapterWordCountMin;
    delete merged.chapterWordCountMax;

    const draftCompanies = merged.companies as CompanyProfile[] | undefined;
    const companies =
      Array.isArray(draftCompanies) && draftCompanies.length > 0
        ? draftCompanies
        : initialState.companies;
    let activeCompanyId =
      typeof merged.activeCompanyId === 'string'
        ? merged.activeCompanyId
        : initialState.activeCompanyId;
    if (!companies.some((c) => c.id === activeCompanyId)) {
      activeCompanyId = companies[0]?.id ?? 'default';
    }

    return {
      ...initialState,
      ...merged,
      companies,
      activeCompanyId,
    } as AppState;
  });

  const updateStep = useCallback((step: number) => {
    setState((prev) => {
      const next = { ...prev, currentStep: step };
      draftStorage.saveDraft({ currentStep: step });
      return next;
    });
  }, []);

  const updateFileContent = useCallback((fileContent: string) => {
    setState((prev) => {
      const next = { ...prev, fileContent };
      draftStorage.saveDraft({ fileContent });
      return next;
    });
  }, []);

  const updateAnalysisResults = useCallback((overview: string, requirements: string) => {
    setState((prev) => {
      const next = {
        ...prev,
        projectOverview: overview,
        techRequirements: requirements,
      };
      draftStorage.saveDraft({
        projectOverview: overview,
        techRequirements: requirements,
      });
      return next;
    });
  }, []);

  const updateScoringItems = useCallback((scoringItems: TechnicalRequirementGroup[]) => {
    setState((prev) => {
      const next = { ...prev, scoringItems };
      draftStorage.saveDraft({ scoringItems });
      return next;
    });
  }, []);

  const updateOutline = useCallback((outlineData: OutlineData) => {
    setState((prev) => {
      const next = { ...prev, outlineData };
      draftStorage.saveDraft({ outlineData });
      return next;
    });
  }, []);

  const updateBookWordCountRange = useCallback((min: number, max: number) => {
    setState((prev) => {
      const lo = Math.max(1000, Math.min(min, max));
      const hi = Math.max(lo, Math.max(min, max));
      const next = { ...prev, bookWordCountMin: lo, bookWordCountMax: hi };
      draftStorage.saveDraft({
        bookWordCountMin: lo,
        bookWordCountMax: hi,
      });
      return next;
    });
  }, []);

  const setActiveCompany = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.companies.some((c) => c.id === id)) {
        return prev;
      }
      const next = { ...prev, activeCompanyId: id };
      draftStorage.saveDraft({ activeCompanyId: id });
      return next;
    });
  }, []);

  const addCompany = useCallback((name: string) => {
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    const id = `co_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    setState((prev) => {
      const companies = [...prev.companies, { id, name: trimmed }];
      const next = { ...prev, companies, activeCompanyId: id };
      draftStorage.saveDraft({ companies, activeCompanyId: id });
      return next;
    });
  }, []);

  const renameCompany = useCallback((id: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    setState((prev) => {
      if (!prev.companies.some((c) => c.id === id)) {
        return prev;
      }
      const companies = prev.companies.map((c) =>
        c.id === id ? { ...c, name: trimmed } : c
      );
      const next = { ...prev, companies };
      draftStorage.saveDraft({ companies });
      return next;
    });
  }, []);

  const removeCompany = useCallback((id: string) => {
    if (id === 'default') {
      return;
    }
    setState((prev) => {
      if (prev.companies.length <= 1) {
        return prev;
      }
      const companies = prev.companies.filter((c) => c.id !== id);
      if (companies.length === 0) {
        return prev;
      }
      let activeCompanyId = prev.activeCompanyId;
      if (activeCompanyId === id) {
        activeCompanyId =
          companies.find((c) => c.id === 'default')?.id ?? companies[0].id;
      }
      const next = { ...prev, companies, activeCompanyId };
      draftStorage.saveDraft({ companies, activeCompanyId });
      return next;
    });
  }, []);

  const nextStep = useCallback(() => {
    setState((prev) => {
      const nextStepValue = Math.min(prev.currentStep + 1, 2);
      const next = { ...prev, currentStep: nextStepValue };
      draftStorage.saveDraft({ currentStep: nextStepValue });
      return next;
    });
  }, []);

  const prevStep = useCallback(() => {
    setState((prev) => {
      const prevStepValue = Math.max(prev.currentStep - 1, 0);
      const next = { ...prev, currentStep: prevStepValue };
      draftStorage.saveDraft({ currentStep: prevStepValue });
      return next;
    });
  }, []);

  const resetState = useCallback(() => {
    setState({ ...initialState, scoringItems: [] });
  }, []);

  const openLocalDb = useCallback(() => {
    setState((prev) => ({
      ...prev,
      uiMode: 'localDb',
      localDbView: 'dbFiles',
    }));
  }, []);

  const backToSteps = useCallback(() => {
    setState((prev) => ({
      ...prev,
      uiMode: 'steps',
    }));
  }, []);

  const setLocalDbView = useCallback((view: AppState['localDbView']) => {
    setState((prev) => ({
      ...prev,
      localDbView: view,
    }));
  }, []);

  return {
    state,
    updateStep,
    updateFileContent,
    updateAnalysisResults,
    updateScoringItems,
    updateOutline,
    updateBookWordCountRange,
    setActiveCompany,
    addCompany,
    renameCompany,
    removeCompany,
    nextStep,
    prevStep,
    resetState,
    openLocalDb,
    backToSteps,
    setLocalDbView,
  };
};
