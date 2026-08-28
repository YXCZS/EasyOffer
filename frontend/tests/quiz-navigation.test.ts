import assert from 'node:assert/strict'
import test from 'node:test'
import { clampQuizViewIndex, nextReviewViewIndex, previousQuizViewIndex, syncQuizViewIndex } from '../src/pages/quiz/navigation.ts'

test('initial view follows the persisted frontier even while the next question is loading', () => {
  assert.equal(clampQuizViewIndex(3, 3, 3), 3)
})

test('previous navigation never moves before the first question', () => {
  assert.equal(previousQuizViewIndex(0), 0)
  assert.equal(previousQuizViewIndex(2), 1)
})

test('a user at the frontier follows a persisted progress advance', () => {
  assert.equal(syncQuizViewIndex(2, 2, 3, 4), 3)
})

test('polling and appended questions do not interrupt historical review', () => {
  assert.equal(syncQuizViewIndex(0, 2, 3, 4), 0)
  assert.equal(syncQuizViewIndex(1, 3, 3, 5), 1)
})

test('review navigation can move forward only as far as the persisted frontier', () => {
  assert.equal(nextReviewViewIndex(0, 3), 1)
  assert.equal(nextReviewViewIndex(3, 3), 3)
})
