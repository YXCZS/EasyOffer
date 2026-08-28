import Taro from '@tarojs/taro'
import { AnswerRecord, Difficulty, Question, Quiz, Report, Role } from '../types/domain'
import { clearStoredAuth, getGuestToken, getStoredAuth, StoredAuth, UserSummary } from './auth-storage'

// Keep this as a compile-time constant: WeChat mini-programs do not expose Node's
// `process` global at runtime. Change it to the deployed HTTPS API before release.
const API_BASE_URL = 'http://127.0.0.1:8000/api/v1'

interface ApiResponse<T> { code: number; message: string; data: T }

export class ApiRequestError extends Error {
  constructor(message: string, public readonly statusCode: number) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

async function request<T>(url: string, method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', data?: unknown): Promise<T> {
  const auth = getStoredAuth()
  const response = await Taro.request<ApiResponse<T>>({
    url: `${API_BASE_URL}${url}`,
    method,
    data,
    header: { ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}), 'X-Guest-Token': getGuestToken() },
    timeout: 120000,
  })
  if (response.statusCode === 401) {
    clearStoredAuth()
    throw new ApiRequestError('登录状态已失效，请重新登录', response.statusCode)
  }
  const body = response.data
  if (response.statusCode < 200 || response.statusCode >= 300 || body.code !== 0) {
    const errorBody = body as ApiResponse<T> & { detail?: string }
    throw new ApiRequestError(errorBody.message || errorBody.detail || '请求失败，请稍后重试', response.statusCode)
  }
  return body.data
}

export function loginWithCode(code: string) {
  return request<StoredAuth>('/user/login', 'POST', { code })
}

export function getProfile() {
  return request<UserProfile>('/user/profile', 'GET')
}

export interface KnowledgeDocument {
  document_id: string
  original_name: string
  mime_type: string
  file_size: number
  status: 'processing' | 'ready' | 'failed'
  error_message?: string | null
  chunk_count: number
  embedding_model?: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeDocumentPage { items: KnowledgeDocument[]; total: number; page: number; page_size: number }

export function getKnowledgeDocuments(page = 1, pageSize = 50) {
  return request<KnowledgeDocumentPage>(`/knowledge/documents?page=${page}&page_size=${pageSize}`, 'GET')
}

export function retryKnowledgeDocument(documentId: string) {
  return request<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(documentId)}/retry`, 'POST')
}

export function deleteKnowledgeDocument(documentId: string) {
  return request<{ deleted: boolean }>(`/knowledge/documents/${encodeURIComponent(documentId)}`, 'DELETE')
}

export function renameKnowledgeDocument(documentId: string, originalName: string) {
  // PUT is supported consistently by wx.request; the backend keeps PATCH for existing clients.
  return request<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(documentId)}`, 'PUT', { original_name: originalName })
}

export function uploadKnowledgeDocument(filePath: string, fileName: string, onProgress?: (progress: number) => void): Promise<KnowledgeDocument> {
  const auth = getStoredAuth()
  return new Promise((resolve, reject) => {
    if (!auth?.token) { reject(new Error('请先登录')); return }
    const task = Taro.uploadFile({
      url: `${API_BASE_URL}/knowledge/documents`, filePath, name: 'file', header: { Authorization: `Bearer ${auth.token}` },
      formData: { original_name: fileName },
      success: (response) => {
        try {
          const body = typeof response.data === 'string' ? JSON.parse(response.data) as ApiResponse<KnowledgeDocument> : response.data as ApiResponse<KnowledgeDocument>
          if (response.statusCode < 200 || response.statusCode >= 300 || body.code !== 0) reject(new Error(body.message || '文档上传失败'))
          else resolve(body.data)
        } catch (_) { reject(new Error('文档上传响应格式错误')) }
      },
      fail: () => reject(new Error('文档上传失败，请检查网络后重试')),
    })
    task.onProgressUpdate?.(({ progress }) => onProgress?.(Math.max(0, Math.min(100, progress))))
  })
}

export function updateProfile(data: { nickname?: string; avatar_url?: string }) {
  return request<UserProfile>('/user/profile', 'PUT', data)
}

export function uploadAvatar(filePath: string): Promise<UserProfile> {
  const auth = getStoredAuth()
  return new Promise((resolve, reject) => {
    if (!auth?.token) {
      reject(new Error('请先登录后再上传头像'))
      return
    }
    Taro.uploadFile({
      url: `${API_BASE_URL}/user/avatar`,
      filePath,
      name: 'image',
      header: { Authorization: `Bearer ${auth.token}` },
      success: (response) => {
        try {
          const body = typeof response.data === 'string' ? JSON.parse(response.data) as ApiResponse<UserProfile> : response.data as ApiResponse<UserProfile>
          if (response.statusCode === 401) {
            clearStoredAuth()
            reject(new Error('登录状态已失效，请重新登录'))
          } else if (body.code !== 0) {
            reject(new Error(body.message || '头像上传失败，请稍后重试'))
          } else {
            resolve(body.data)
          }
        } catch (_) {
          reject(new Error('头像上传响应格式错误'))
        }
      },
      fail: () => reject(new Error('头像上传失败，请检查网络后重试')),
    })
  })
}

export function getHistory(page = 1, pageSize = 10) {
  return request<HistoryPage>(`/user/quizzes?page=${page}&page_size=${pageSize}`, 'GET')
}

export function getHistoryDetail(quizId: string) {
  return request<HistoryDetail>(`/user/quizzes/${encodeURIComponent(quizId)}`, 'GET')
}

export function generateQuiz(
  userInput: string,
  role: Role,
  difficulty: Difficulty,
  options?: { documentId?: string; knowledgeOnly?: boolean; generateImages?: boolean; usePersonalKnowledge?: boolean },
) {
  const payload: Record<string, unknown> = { user_input: userInput, role, difficulty, question_count: 6 }
  payload.generate_images = options?.generateImages ?? false
  payload.use_personal_knowledge = options?.usePersonalKnowledge ?? Boolean(options?.documentId)
  if (options?.documentId) {
    payload.document_id = options.documentId
    payload.knowledge_only = options.knowledgeOnly ?? true
  }
  return request<Quiz>('/quiz/generate', 'POST', payload)
}

export type GenerationTaskStatus = 'queued' | 'generating' | 'completed' | 'failed' | 'expired'

export interface QuizGenerationTaskSnapshot {
  task_id: string
  status: GenerationTaskStatus
  generated_count: number
  total_count: number
  version: number
  progress_version: number
  current_index: number
  questions: Question[]
  answer_records: AnswerRecord[]
  title: string
  summary: string
  quiz: Quiz | null
  error_message?: string | null
  retryable: boolean
  updated_at: string
}

export function createQuizGenerationTask(
  userInput: string,
  role: Role,
  difficulty: Difficulty,
  options?: { documentId?: string; knowledgeOnly?: boolean; generateImages?: boolean; usePersonalKnowledge?: boolean },
) {
  const payload: Record<string, unknown> = { user_input: userInput, role, difficulty, question_count: 6 }
  payload.generate_images = options?.generateImages ?? false
  payload.use_personal_knowledge = options?.usePersonalKnowledge ?? Boolean(options?.documentId)
  if (options?.documentId) {
    payload.document_id = options.documentId
    payload.knowledge_only = options.knowledgeOnly ?? true
  }
  return request<QuizGenerationTaskSnapshot>('/quiz/generation-tasks', 'POST', payload)
}

export function getQuizGenerationTask(taskId: string) {
  return request<QuizGenerationTaskSnapshot>(`/quiz/generation-tasks/${encodeURIComponent(taskId)}`, 'GET')
}

export function saveQuizGenerationProgress(
  taskId: string,
  data: { current_index: number; answer_records: AnswerRecord[]; progress_version: number },
) {
  return request<QuizGenerationTaskSnapshot>(`/quiz/generation-tasks/${encodeURIComponent(taskId)}/progress`, 'PUT', data)
}

export function retryQuizGenerationTask(taskId: string) {
  return request<QuizGenerationTaskSnapshot>(`/quiz/generation-tasks/${encodeURIComponent(taskId)}/retry`, 'POST')
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

export interface IncompleteQuizItem {
  quiz_id: string
  title: string
  topic: string
  role: Role
  difficulty: Difficulty
  status: 'in_progress' | 'ready_for_report'
  answered_count: number
  total_questions: number
  current_index: number
  updated_at: string
}

export interface IncompleteQuizList { items: IncompleteQuizItem[] }

export interface QuizProgressDetail {
  quiz: Quiz
  status: 'in_progress' | 'ready_for_report' | 'completed' | 'abandoned'
  current_index: number
  answered_count: number
  total_questions: number
  answer_records: AnswerRecord[]
  version: number
  updated_at: string
  last_error?: string | null
}

export function getIncompleteQuizzes() {
  return request<IncompleteQuizList>('/user/quizzes/incomplete', 'GET')
}

export function getQuizProgress(quizId: string) {
  return request<QuizProgressDetail>(`/user/quizzes/${encodeURIComponent(quizId)}/progress`, 'GET')
}

export function saveQuizProgress(quizId: string, data: { current_index: number; answer_records: AnswerRecord[]; version: number }) {
  return request<QuizProgressDetail>(`/user/quizzes/${encodeURIComponent(quizId)}/progress`, 'PUT', data)
}

export function abandonQuizProgress(quizId: string) {
  return request<{ abandoned: boolean }>(`/user/quizzes/${encodeURIComponent(quizId)}/progress`, 'DELETE')
}

export interface UserProfile extends UserSummary {
  quiz_count: number
  correct_count: number
  average_accuracy: number
}

export interface HistoryItem {
  quiz_id: string
  title: string
  accuracy: number
  question_count: number
  created_at: string
}

export interface HistoryPage {
  items: HistoryItem[]
  total: number
  page: number
  page_size: number
}

export interface HistoryDetail {
  quiz: { quiz_id: string; title: string; summary: string; topic: string; questions: Quiz['questions']; created_at: string }
  answer_records: AnswerRecord[]
  report: Report | null
}
