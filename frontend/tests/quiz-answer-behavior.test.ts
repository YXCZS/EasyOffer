import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildQuestionResults,
  buildQuestionReviewRows,
  canSubmitAnswer,
  isAnswerCorrect,
  mergeAnswerRecords,
  updateSelectedAnswers,
} from '../src/utils/quiz-answers.ts'
import type { Question, Quiz } from '../src/types/domain.ts'

const baseQuestion: Question = {
  id: 'q1',
  type: 'single',
  stem: '题目',
  options: [
    { key: 'A', text: '选项 A' },
    { key: 'B', text: '选项 B' },
    { key: 'C', text: '选项 C' },
    { key: 'D', text: '选项 D' },
  ],
  answer: ['A'],
  explanation: '解析',
  option_explanations: { A: 'A', B: 'B', C: 'C', D: 'D' },
  knowledge_point: '知识点',
  misconception: '误区',
  difficulty: 'medium',
  version_context: '当前版本',
}

test('multiple choice toggles several options independently', () => {
  let selected: string[] = []
  selected = updateSelectedAnswers('multiple', selected, 'A')
  selected = updateSelectedAnswers('multiple', selected, 'C')
  assert.deepEqual(selected, ['A', 'C'])
  selected = updateSelectedAnswers('multiple', selected, 'A')
  assert.deepEqual(selected, ['C'])
})

test('single and judge choices replace the previous selection', () => {
  assert.deepEqual(updateSelectedAnswers('single', ['A'], 'B'), ['B'])
  assert.deepEqual(updateSelectedAnswers('judge', ['A'], 'B'), ['B'])
})

test('submitted answer stays read only', () => {
  const selected = ['A', 'C']
  assert.equal(updateSelectedAnswers('multiple', selected, 'B', true), selected)
})

test('answer correctness uses unordered exact set equality', () => {
  assert.equal(isAnswerCorrect(['C', 'A'], ['A', 'C']), true)
  assert.equal(isAnswerCorrect(['A'], ['A', 'C']), false)
  assert.equal(isAnswerCorrect(['A', 'B', 'C'], ['A', 'C']), false)
  assert.equal(isAnswerCorrect(['A', 'A'], ['A', 'C']), false)
})

test('empty or read-only answers cannot be submitted', () => {
  assert.equal(canSubmitAnswer([], false), false)
  assert.equal(canSubmitAnswer(['A'], true), false)
  assert.equal(canSubmitAnswer(['A', 'C'], false), true)
})

test('progress merge preserves every selected answer for multiple choice', () => {
  const merged = mergeAnswerRecords(
    [{ question_id: 'q1', selected_answers: ['A'], duration_ms: 10 }],
    [{ question_id: 'q5', selected_answers: ['C', 'A'], duration_ms: 20 }],
  )
  assert.deepEqual(merged[1].selected_answers, ['C', 'A'])

  const conflictMerged = mergeAnswerRecords(
    [{ question_id: 'q5', selected_answers: ['A'], duration_ms: 10 }],
    [{ question_id: 'q5', selected_answers: ['A', 'C'], duration_ms: 20 }],
  )
  assert.deepEqual(conflictMerged, [
    { question_id: 'q5', selected_answers: ['A', 'C'], duration_ms: 20 },
  ])
})

test('report fallback restores multiple and judge answer details', () => {
  const multiple: Question = { ...baseQuestion, id: 'q5', type: 'multiple', answer: ['A', 'C'] }
  const judge: Question = {
    ...baseQuestion,
    id: 'q6',
    type: 'judge',
    options: [{ key: 'A', text: '正确' }, { key: 'B', text: '错误' }],
    option_explanations: { A: '正确', B: '错误' },
    answer: ['A'],
  }
  const quiz = {
    quiz_id: 'quiz-1', title: '测试', summary: '测试', topic: '测试', role: 'general',
    difficulty: 'medium', questions: [multiple, judge], model_version: 'test', prompt_version: 'test',
  } satisfies Quiz

  const results = buildQuestionResults(quiz, [
    { question_id: 'q5', selected_answers: ['C', 'A'], duration_ms: 10 },
    { question_id: 'q6', selected_answers: ['B'], duration_ms: 10 },
  ])

  assert.equal(results[0].status, 'correct')
  assert.deepEqual(results[0].selected_answer_texts, ['选项 C', '选项 A'])
  assert.equal(results[1].status, 'incorrect')
  assert.deepEqual(results[1].selected_answer_texts, ['错误'])
  assert.deepEqual(results[1].correct_answer_texts, ['正确'])

  const historyRows = buildQuestionReviewRows(quiz, [
    { question_id: 'q5', selected_answers: ['C', 'A'], duration_ms: 10 },
    { question_id: 'q6', selected_answers: ['B'], duration_ms: 10 },
  ])
  assert.equal(historyRows[0].question_type_label, '多选题')
  assert.equal(historyRows[1].question_type_label, '判断题')
  assert.equal(historyRows[1].explanation, '解析')
})
