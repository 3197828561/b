import { OutlineItem, TechnicalRequirementGroup } from '../types';

export interface CoverageSummary {
  total: number;
  coveredCount: number;
  uncoveredCount: number;
  coverageRate: number;
  uncovered: TechnicalRequirementGroup[];
}

/** 与后端 coverage_service 一致的轻量前端检查（离线预览用） */
export function checkScoringCoverageLocal(
  groups: TechnicalRequirementGroup[],
  outline: OutlineItem[]
): CoverageSummary {
  if (!groups.length) {
    return {
      total: 0,
      coveredCount: 0,
      uncoveredCount: 0,
      coverageRate: 1,
      uncovered: [],
    };
  }

  const leaves = collectLeaves(outline);
  const uncovered: TechnicalRequirementGroup[] = [];
  let coveredCount = 0;

  for (const group of groups) {
    if (leaves.some((leaf) => leafCoversGroup(leaf, group))) {
      coveredCount += 1;
    } else {
      uncovered.push(group);
    }
  }

  const total = groups.length;
  return {
    total,
    coveredCount,
    uncoveredCount: uncovered.length,
    coverageRate: total ? coveredCount / total : 1,
    uncovered,
  };
}

function collectLeaves(items: OutlineItem[]): OutlineItem[] {
  const leaves: OutlineItem[] = [];
  for (const item of items) {
    if (item.children?.length) {
      leaves.push(...collectLeaves(item.children));
    } else {
      leaves.push(item);
    }
  }
  return leaves;
}

function tokenize(text: string): Set<string> {
  const lower = text.toLowerCase();
  const words = lower.match(/[a-z0-9]+/g) ?? [];
  const han = text.match(/[\u4e00-\u9fff]/g) ?? [];
  const set = new Set([...words, ...han]);
  for (let i = 0; i < text.length - 1; i++) {
    const pair = text.slice(i, i + 2);
    if (/^[\u4e00-\u9fff]{2}$/.test(pair)) {
      set.add(pair);
    }
  }
  return set;
}

function leafCoversGroup(leaf: OutlineItem, group: TechnicalRequirementGroup): boolean {
  const rid = (group.requirement_id || '').trim();
  const gtitle = (group.title || '').trim();
  if (!gtitle && !rid) {
    return false;
  }
  if (rid && leaf.source_requirement_id === rid) {
    return true;
  }
  const blob = `${leaf.title} ${leaf.description ?? ''} ${leaf.source_requirement_title ?? ''}`;
  const gTokens = tokenize(gtitle);
  const overlap = Array.from(gTokens).filter((t) => tokenize(blob).has(t));
  const need = gTokens.size >= 4 ? 2 : 1;
  return overlap.length >= need;
}
