import Taro from '@tarojs/taro'
import { AnswerRecord, Difficulty, Quiz, Report, Role } from '../types/domain'

// Keep this as a compile-time constant: WeChat mini-programs do not expose Node's
// `process` global at runtime. Change it to the deployed HTTPS API before release.
const API_BASE_URL = 'http://127.0.0.1:8000/api/v1'

interface ApiResponse<T> { code: number; message: string; data: T }

async function request<T>(url: string, method: 'GET' | 'POST', data?: unknown): Promise<T> {
  const response = await Taro.request<ApiResponse<T>>({ url: `${API_BASE_URL}${url}`, method, data })
  const body = response.data
  if (body.code !== 0) throw new Error(body.message)
  return body.data
}

export function generateQuiz(userInput: string, role: Role, difficulty: Difficulty) {
  return request<Quiz>('/quiz/generate', 'POST', { user_input: userInput, role, difficulty, question_count: 6 })
}

export function generateReport(quiz: Quiz, answerRecords: AnswerRecord[]) {
  return request<Report>('/report/generate', 'POST', {
    quiz_id: quiz.quiz_id,
    topic: quiz.topic,
    role: quiz.role,
    questions: quiz.questions,
    answer_records: answerRecords,
  })
}
