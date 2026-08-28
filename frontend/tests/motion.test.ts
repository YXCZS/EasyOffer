import assert from 'node:assert/strict'
import test from 'node:test'
import { advanceMotionStage, clampMotionStage, motionDirection } from '../src/utils/motion.ts'

test('motion stages stay within available steps', () => {
  assert.equal(clampMotionStage(-2, 4), 0)
  assert.equal(clampMotionStage(9, 4), 3)
  assert.equal(clampMotionStage(2, 4), 2)
})

test('async stage updates never move the visual state backwards', () => {
  assert.equal(advanceMotionStage(2, 1, 4), 2)
  assert.equal(advanceMotionStage(1, 3, 4), 3)
})

test('question transitions follow navigation direction', () => {
  assert.equal(motionDirection(1, 2), 'forward')
  assert.equal(motionDirection(2, 1), 'backward')
  assert.equal(motionDirection(2, 2), 'steady')
})
