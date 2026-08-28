export type MotionDirection = 'forward' | 'backward' | 'steady'

export function clampMotionStage(stage: number, total: number) {
  if (total <= 0) return 0
  return Math.min(Math.max(0, Math.trunc(stage)), total - 1)
}

export function advanceMotionStage(current: number, incoming: number, total: number) {
  return Math.max(clampMotionStage(current, total), clampMotionStage(incoming, total))
}

export function motionDirection(from: number, to: number): MotionDirection {
  if (to > from) return 'forward'
  if (to < from) return 'backward'
  return 'steady'
}
