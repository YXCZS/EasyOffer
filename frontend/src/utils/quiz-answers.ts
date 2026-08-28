import type { AnswerRecord, QuestionResult, QuestionType, Quiz } from '../types/domain'

export function updateSelectedAnswers(
  questionType: QuestionType,
  current: string[],
  key: string,
  readOnly = false,
): string[] {
  if (readOnly) return current
  if (questionType !== 'multiple') return [key]
  return current.includes(key)
    ? current.filter((item) => item !== key)
    : [...current, key]
}

export function isAnswerCorrect(selected: string[], expected: string[]): boolean {
  const selectedSet = new Set(selected)
  const expectedSet = new Set(expected)
  return selected.length === selectedSet.size
    && expected.length === expectedSet.size
    && selectedSet.size === expectedSet.size
    && [...selectedSet].every((key) => expectedSet.has(key))
}

export function canSubmitAnswer(selected: string[], readOnly = false): boolean {
  return !readOnly && selected.length > 0
}

export function mergeAnswerRecords(
  serverAnswers: AnswerRecord[],
  localAnswers: AnswerRecord[],
): AnswerRecord[] {
  const merged = serverAnswers.map((answer) => ({
    ...answer,
    selected_answers: [...answer.selected_answers],
  }))
  for (const answer of localAnswers) {
    const copy = { ...answer, selected_answers: [...answer.selected_answers] }
    const index = merged.findIndex((item) => item.question_id === answer.question_id)
    if (index >= 0) merged[index] = copy
    else merged.push(copy)
  }
  return merged
}

export function buildQuestionResults(
  quiz: Pick<Quiz, 'questions'> | null,
  answers: AnswerRecord[],
): QuestionResult[] {
  if (!quiz) return []
  const records = new Map(answers.map((answer) => [answer.question_id, answer]))
  return quiz.questions.map((question, index) => {
    const record = records.get(question.id)
    const optionMap = Object.fromEntries(question.options.map((option) => [option.key, option.text]))
    const selected = record?.selected_answers ?? []
    return {
      question_id: question.id,
      question_number: index + 1,
      stem: question.stem,
      knowledge_point: question.knowledge_point,
      status: !record ? 'unanswered' : isAnswerCorrect(selected, question.answer) ? 'correct' : 'incorrect',
      selected_answers: selected,
      selected_answer_texts: selected.map((key) => optionMap[key]).filter(Boolean),
      correct_answers: question.answer,
      correct_answer_texts: question.answer.map((key) => optionMap[key]).filter(Boolean),
      duration_ms: record?.duration_ms ?? 0,
      explanation: question.explanation,
    }
  })
}

export function questionTypeLabel(questionType: QuestionType): string {
  if (questionType === 'multiple') return '多选题'
  if (questionType === 'judge') return '判断题'
  return '单选题'
}

export type QuestionReviewRow = QuestionResult & {
  question_type: QuestionType
  question_type_label: string
}

export function buildQuestionReviewRows(
  quiz: Pick<Quiz, 'questions'>,
  answers: AnswerRecord[],
): QuestionReviewRow[] {
  const questions = new Map(quiz.questions.map((question) => [question.id, question]))
  return buildQuestionResults(quiz, answers).map((result) => {
    const question = questions.get(result.question_id)
    const questionType = question?.type ?? 'single'
    return {
      ...result,
      question_type: questionType,
      question_type_label: questionTypeLabel(questionType),
    }
  })
}
