export function clampQuizViewIndex(index: number, frontierIndex: number, loadedQuestionCount: number) {
  const maxIndex = Math.max(0, frontierIndex, loadedQuestionCount - 1)
  return Math.min(Math.max(0, index), maxIndex)
}

export function syncQuizViewIndex(
  viewIndex: number,
  previousFrontierIndex: number,
  nextFrontierIndex: number,
  loadedQuestionCount: number,
) {
  const nextIndex = viewIndex >= previousFrontierIndex ? nextFrontierIndex : viewIndex
  return clampQuizViewIndex(nextIndex, nextFrontierIndex, loadedQuestionCount)
}

export function previousQuizViewIndex(viewIndex: number) {
  return Math.max(0, viewIndex - 1)
}

export function nextReviewViewIndex(viewIndex: number, frontierIndex: number) {
  return Math.min(frontierIndex, viewIndex + 1)
}
