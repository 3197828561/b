/**
 * 将「全书正文目标总字数」区间按末级章节数均摊为单章区间（传给模型）。
 */
export function allocatePerChapterFromBookTotal(
  bookMin: number,
  bookMax: number,
  leafCount: number
): { perChapterMin: number; perChapterMax: number } {
  if (leafCount <= 0) {
    return { perChapterMin: 800, perChapterMax: 2500 };
  }
  const perChapterMin = Math.max(50, Math.floor(bookMin / leafCount));
  const perChapterMax = Math.max(perChapterMin, Math.floor(bookMax / leafCount));
  return { perChapterMin, perChapterMax };
}
