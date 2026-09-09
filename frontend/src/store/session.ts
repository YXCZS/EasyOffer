import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { ApiRequestError, getQuizGenerationTask, getQuizProgress, QuizGenerationTaskSnapshot, saveQuizGenerationProgress, saveQuizProgress } from '../services/api'
import { AnswerRecord, Difficulty, Question, Quiz, Report, Role } from '../types/domain'
import { getStoredAuth } from '../services/auth-storage'
import { mergeAnswerRecords } from '../utils/quiz-answers'

const STORAGE_KEY = 'easyoffer-session-v2'
const LEGACY_STORAGE_KEY = 'easyoffer-session-v1'
const generationProgressQueues = new Map<string, Promise<void>>()
const quizProgressQueues = new Map<string, Promise<void>>()

function enqueueGenerationProgress(taskId: string, operation: () => Promise<void>): Promise<void> {
  const previous = generationProgressQueues.get(taskId) || Promise.resolve()
  const next = previous.catch(() => undefined).then(operation)
  generationProgressQueues.set(taskId, next)
  return next.finally(() => {
    if (generationProgressQueues.get(taskId) === next) generationProgressQueues.delete(taskId)
  })
}

function enqueueQuizProgress(quizId: string, operation: () => Promise<void>): Promise<void> {
  const previous = quizProgressQueues.get(quizId) || Promise.resolve()
  const next = previous.catch(() => undefined).then(operation)
  quizProgressQueues.set(quizId, next)
  return next.finally(() => {
    if (quizProgressQueues.get(quizId) === next) quizProgressQueues.delete(quizId)
  })
}

export type PracticeStatus = 'in_progress' | 'ready_for_report' | 'completed' | 'abandoned'
export type QuizDraft = Omit<Quiz, 'questions'> & { questions: Question[] }

export interface PracticeSession {
  quiz: QuizDraft
  documentId?: string
  documentName?: string
  generationTaskId?: string
  generationStatus?: 'queued' | 'generating' | 'completed' | 'failed' | 'expired' | 'cancelled'
  generationVersion?: number
  progressVersion?: number
  formalProgressSynced?: boolean
  totalQuestions?: number
  currentIndex: number
  answers: AnswerRecord[]
  report: Report | null
  status: PracticeStatus
  version: number
  updatedAt: number
}

interface SessionState {
  topic: string
  role: Role
  difficulty: Difficulty
  generateImages: boolean
  usePersonalKnowledge: boolean
  documentId: string | null
  documentName: string | null
  generationTaskId: string | null
  generationStatus: PracticeSession['generationStatus'] | null
  generationVersion: number
  generationProgressVersion: number
  generatedCount: number
  totalQuestionCount: number
  quiz: QuizDraft | null
  currentIndex: number
  answers: AnswerRecord[]
  report: Report | null
  activeQuizId: string | null
  practices: Record<string, PracticeSession>
  setTopic: (topic: string) => void
  setRole: (role: Role) => void
  setDifficulty: (difficulty: Difficulty) => void
  setGenerateImages: (enabled: boolean) => void
  setUsePersonalKnowledge: (enabled: boolean) => void
  setDocumentContext: (documentId: string | null, documentName?: string | null) => void
  setQuiz: (quiz: Quiz) => void
  applyGenerationSnapshot: (taskId: string, snapshot: QuizGenerationTaskSnapshot) => void
  selectPractice: (quizId: string) => void
  recordAnswer: (answer: AnswerRecord) => void
  advanceQuestion: () => void
  setReport: (report: Report) => void
  saveActiveProgress: () => Promise<void>
  restorePractice: (quizId: string) => Promise<void>
  removePractice: (quizId?: string) => void
  clearPractices: () => void
  reset: () => void
}

const initial = {
  topic: '',
  role: 'general' as Role,
  difficulty: 'medium' as Difficulty,
  generateImages: false,
  usePersonalKnowledge: false,
  documentId: null as string | null,
  documentName: null as string | null,
  generationTaskId: null as string | null,
  generationStatus: null as PracticeSession['generationStatus'] | null,
  generationVersion: 1,
  generationProgressVersion: 1,
  generatedCount: 0,
  totalQuestionCount: 6,
  quiz: null as QuizDraft | null,
  currentIndex: 0,
  answers: [] as AnswerRecord[],
  report: null as Report | null,
  activeQuizId: null as string | null,
  practices: {} as Record<string, PracticeSession>,
}

function serialize(state: Pick<SessionState, 'topic' | 'role' | 'difficulty' | 'generateImages' | 'usePersonalKnowledge' | 'documentId' | 'documentName' | 'generationTaskId' | 'generationStatus' | 'generationVersion' | 'generationProgressVersion' | 'generatedCount' | 'totalQuestionCount' | 'activeQuizId' | 'practices'>) {
  Taro.setStorageSync(STORAGE_KEY, state)
}

function syncActive(set: (value: Partial<SessionState>) => void, practices: Record<string, PracticeSession>, activeQuizId: string | null) {
  const active = activeQuizId ? practices[activeQuizId] : undefined
  set({
    activeQuizId,
    practices,
    quiz: active?.quiz || null,
    currentIndex: active?.currentIndex || 0,
    answers: active?.answers || [],
    report: active?.report || null,
    generationTaskId: active?.generationTaskId || null,
    generationStatus: active?.generationStatus || null,
    generationVersion: active?.generationVersion || 1,
    generationProgressVersion: active?.progressVersion || 1,
    generatedCount: active?.quiz.questions.length || 0,
    totalQuestionCount: active?.totalQuestions || 6,
  })
}

export const useSession = create<SessionState>((set, get) => ({
  ...initial,
  setTopic: (topic) => { set({ topic }); serialize({ ...get(), topic }) },
  setRole: (role) => { set({ role }); serialize({ ...get(), role }) },
  setDifficulty: (difficulty) => { set({ difficulty }); serialize({ ...get(), difficulty }) },
  setGenerateImages: (generateImages) => { set({ generateImages }); serialize({ ...get(), generateImages }) },
  setUsePersonalKnowledge: (usePersonalKnowledge) => { set({ usePersonalKnowledge }); serialize({ ...get(), usePersonalKnowledge }) },
  setDocumentContext: (documentId, documentName = null) => {
    set({ documentId, documentName })
    serialize({ ...get(), documentId, documentName })
  },
  setQuiz: (quiz) => {
    const state = get()
    const evidenceDocumentId = quiz.evidence_meta?.document_id
    const practice: PracticeSession = {
      quiz,
      documentId: state.documentId || evidenceDocumentId || undefined,
      documentName: state.documentName || undefined,
      currentIndex: 0,
      answers: [],
      report: null,
      status: 'in_progress',
      version: 1,
      formalProgressSynced: true,
      updatedAt: Date.now(),
    }
    const practices = { ...get().practices, [quiz.quiz_id]: practice }
    syncActive(set, practices, quiz.quiz_id)
    serialize({ ...get(), activeQuizId: quiz.quiz_id, practices })
  },
  applyGenerationSnapshot: (taskId, snapshot) => {
    const state = get()
    const existingId = state.activeQuizId
    const existing = existingId ? state.practices[existingId] : undefined
    const previous = existing?.generationTaskId === taskId ? existing : undefined
    if (previous && snapshot.version < (previous.generationVersion || 1)) {
      // Poll responses may arrive out of order. Do not roll back a newer task
      // snapshot or replace already generated questions with an older list.
      return
    }
    const seedQuiz: QuizDraft = snapshot.quiz || previous?.quiz || {
      quiz_id: `task_${taskId}`,
      title: snapshot.title || `${state.topic} 面试练习`,
      summary: snapshot.summary || `围绕 ${state.topic} 的技术面试题`,
      topic: state.topic,
      role: state.role,
      difficulty: state.difficulty,
      questions: snapshot.questions,
      model_version: 'pending',
      prompt_version: 'incremental-v1',
    }
    // Poll responses can arrive out of order. Keep the newest question list
    // while retaining the completed quiz metadata once finalization happens.
    const knownQuestions = new Map((previous?.quiz.questions || []).map((item) => [item.id, item]))
    for (const item of snapshot.questions) knownQuestions.set(item.id, item)
    const mergedQuestions = Array.from(knownQuestions.values())
    const quiz: QuizDraft = {
      ...seedQuiz,
      questions: mergedQuestions.length >= snapshot.questions.length ? mergedQuestions : snapshot.questions,
    }
    const key = snapshot.quiz?.quiz_id || previous?.quiz.quiz_id || `task_${taskId}`
    const mergedAnswers = [...(previous?.answers || [])]
    for (const answer of snapshot.answer_records) {
      const index = mergedAnswers.findIndex((item) => item.question_id === answer.question_id)
      if (index >= 0) mergedAnswers[index] = answer
      else mergedAnswers.push(answer)
    }
    const practice: PracticeSession = {
      quiz,
      documentId: state.documentId || previous?.documentId,
      documentName: state.documentName || previous?.documentName,
      generationTaskId: taskId,
      generationStatus: snapshot.status,
      generationVersion: Math.max(previous?.generationVersion || 1, snapshot.version),
      progressVersion: Math.max(previous?.progressVersion || 1, snapshot.progress_version),
      totalQuestions: snapshot.total_count,
      currentIndex: Math.max(previous?.currentIndex || 0, snapshot.current_index),
      answers: mergedAnswers,
      report: previous?.report || null,
      status: 'in_progress',
      version: previous?.version || 1,
      formalProgressSynced: snapshot.status === 'completed'
        ? Boolean(previous?.formalProgressSynced)
        : previous?.formalProgressSynced,
      updatedAt: Date.now(),
    }
    const practices = { ...state.practices, [key]: practice }
    if (existingId && existingId !== key && previous) delete practices[existingId]
    syncActive(set, practices, key)
    serialize({ ...get(), activeQuizId: key, practices })
  },
  selectPractice: (quizId) => {
    const practice = get().practices[quizId]
    if (!practice) return
    syncActive(set, get().practices, quizId)
    serialize({ ...get(), activeQuizId: quizId })
  },
  recordAnswer: (answer) => {
    const state = get()
    if (!state.activeQuizId || !state.quiz) return
    const current = state.practices[state.activeQuizId]
    const answers = [...current.answers.filter((item) => item.question_id !== answer.question_id), answer]
    const practice = { ...current, answers, updatedAt: Date.now() }
    const practices = { ...state.practices, [state.activeQuizId]: practice }
    syncActive(set, practices, state.activeQuizId)
    serialize({ ...get(), activeQuizId: state.activeQuizId, practices })
  },
  advanceQuestion: () => {
    const state = get()
    if (!state.activeQuizId || !state.quiz) return
    const current = state.practices[state.activeQuizId]
    const maxIndex = current.generationTaskId ? (current.totalQuestions || 6) - 1 : current.quiz.questions.length - 1
    const currentIndex = Math.min(current.currentIndex + 1, maxIndex)
    const practice = { ...current, currentIndex, updatedAt: Date.now() }
    const practices = { ...state.practices, [state.activeQuizId]: practice }
    syncActive(set, practices, state.activeQuizId)
    serialize({ ...get(), activeQuizId: state.activeQuizId, practices })
  },
  setReport: (report) => {
    const state = get()
    if (!state.activeQuizId) { set({ report }); return }
    const current = state.practices[state.activeQuizId]
    if (!current) { set({ report }); return }
    const practice = { ...current, report, status: 'completed' as PracticeStatus, updatedAt: Date.now() }
    const practices = { ...state.practices, [state.activeQuizId]: practice }
    syncActive(set, practices, state.activeQuizId)
    serialize({ ...get(), activeQuizId: state.activeQuizId, practices })
  },
  saveActiveProgress: async () => {
    const state = get()
    if (!state.activeQuizId || !state.quiz) return
    const current = state.practices[state.activeQuizId]
    if (!current || current.status === 'completed' || current.status === 'abandoned') return
    if (current.generationTaskId && current.generationStatus !== 'completed') {
      const taskId = current.generationTaskId
      return enqueueGenerationProgress(taskId, async () => {
        const saveOnce = async (retryAfterConflict: boolean): Promise<void> => {
          const activeId = get().activeQuizId
          const active = activeId ? get().practices[activeId] : undefined
          if (!active || active.generationTaskId !== taskId || active.status === 'completed' || active.status === 'abandoned') return
          try {
            const saved = await saveQuizGenerationProgress(taskId, {
              current_index: active.currentIndex,
              answer_records: active.answers,
              progress_version: active.progressVersion || 1,
            })
            get().applyGenerationSnapshot(taskId, saved)
          } catch (error) {
            if (!(error instanceof ApiRequestError) || error.statusCode !== 409 || retryAfterConflict) throw error
            const latest = await getQuizGenerationTask(taskId)
            get().applyGenerationSnapshot(taskId, latest)
            await saveOnce(true)
          }
        }
        await saveOnce(false)
      })
    }
    if (!getStoredAuth()?.token) return
    const quizId = state.activeQuizId
    return enqueueQuizProgress(quizId, async () => {
      const applySaved = (saved: Awaited<ReturnType<typeof getQuizProgress>>) => {
        const latestState = get()
        const latestLocal = latestState.practices[quizId]
        if (!latestLocal || latestLocal.quiz.quiz_id !== quizId) return
        const practice: PracticeSession = {
          ...latestLocal,
          quiz: saved.quiz,
          currentIndex: Math.max(latestLocal.currentIndex, saved.current_index),
          answers: mergeAnswerRecords(saved.answer_records, latestLocal.answers),
          status: saved.status,
          version: saved.version,
          formalProgressSynced: true,
          updatedAt: Date.now(),
          generationTaskId: latestLocal.generationTaskId,
          generationStatus: latestLocal.generationTaskId ? 'completed' : latestLocal.generationStatus,
          generationVersion: latestLocal.generationVersion,
          progressVersion: latestLocal.progressVersion,
          totalQuestions: saved.total_questions,
        }
        const practices = { ...latestState.practices, [quizId]: practice }
        syncActive(set, practices, latestState.activeQuizId)
        serialize({ ...get(), activeQuizId: latestState.activeQuizId, practices })
      }

      const saveOnce = async (retryAfterConflict: boolean): Promise<void> => {
        const latestLocal = get().practices[quizId]
        if (!latestLocal || latestLocal.quiz.quiz_id !== quizId || latestLocal.status === 'abandoned') return
        if (latestLocal.status === 'completed') return
        try {
          const saved = await saveQuizProgress(quizId, {
            current_index: latestLocal.currentIndex,
            answer_records: latestLocal.answers,
            version: latestLocal.version,
          })
          applySaved(saved)
        } catch (error) {
          if (!(error instanceof ApiRequestError) || error.statusCode !== 409 || retryAfterConflict) throw error
          const latestServer = await getQuizProgress(quizId)
          applySaved(latestServer)
          if (latestServer.status === 'completed' || latestServer.status === 'abandoned') return
          await saveOnce(true)
        }
      }

      const latestLocal = get().practices[quizId]
      if (latestLocal?.generationTaskId && !latestLocal.formalProgressSynced) {
        const latestServer = await getQuizProgress(quizId)
        applySaved(latestServer)
      }
      await saveOnce(false)
    })
  },
  restorePractice: async (quizId) => {
    const existing = get().practices[quizId]
    if (existing) syncActive(set, get().practices, quizId)
    if (!getStoredAuth()?.token) return
    const saved = await getQuizProgress(quizId)
    const current = get().practices[quizId]
    const evidenceDocumentId = saved.quiz.evidence_meta?.document_id
    const practice: PracticeSession = {
      quiz: saved.quiz,
      documentId: current?.documentId || evidenceDocumentId,
      documentName: current?.documentName,
      currentIndex: saved.current_index,
      answers: saved.answer_records,
      report: current?.report || null,
      status: saved.status,
      version: saved.version,
      formalProgressSynced: true,
      updatedAt: Date.now(),
    }
    const practices = { ...get().practices, [quizId]: practice }
    syncActive(set, practices, quizId)
    serialize({ ...get(), activeQuizId: quizId, practices })
  },
  removePractice: (quizId) => {
    const id = quizId || get().activeQuizId
    if (!id) return
    const practices = { ...get().practices }
    delete practices[id]
    const nextId = get().activeQuizId === id ? null : get().activeQuizId
    syncActive(set, practices, nextId)
    serialize({ ...get(), activeQuizId: nextId, practices })
  },
  clearPractices: () => {
    const { topic, role, difficulty } = get()
    set({ ...initial, topic, role, difficulty })
    serialize({ ...initial, topic, role, difficulty, activeQuizId: null, practices: {} })
  },
  reset: () => {
    const id = get().activeQuizId
    const practices = { ...get().practices }
    if (id) delete practices[id]
    set({ ...initial, practices })
    serialize({ ...initial, practices })
  },
}))

export function restoreSession() {
  const saved = Taro.getStorageSync<Partial<SessionState>>(STORAGE_KEY)
  if (saved?.practices) {
    const activeQuizId = saved.activeQuizId || Object.keys(saved.practices)[0] || null
    const practices = saved.practices as Record<string, PracticeSession>
    useSession.setState({ ...initial, ...saved, practices, activeQuizId })
    syncActive(useSession.setState, practices, activeQuizId)
    return
  }
  const legacy = Taro.getStorageSync<Partial<SessionState>>(LEGACY_STORAGE_KEY)
  if (!legacy?.quiz) {
    useSession.setState({ ...initial, topic: legacy?.topic || '', role: legacy?.role || initial.role, difficulty: legacy?.difficulty || initial.difficulty })
    return
  }
  const practice: PracticeSession = {
    quiz: legacy.quiz,
    currentIndex: legacy.currentIndex || 0,
    answers: legacy.answers || [],
    report: legacy.report || null,
    status: legacy.report ? 'completed' : 'in_progress',
    version: 1,
    formalProgressSynced: false,
    updatedAt: Date.now(),
  }
  const practices = { [legacy.quiz.quiz_id]: practice }
  useSession.setState({ ...initial, topic: legacy.topic || legacy.quiz.topic, role: legacy.role || legacy.quiz.role, difficulty: legacy.difficulty || legacy.quiz.difficulty, practices, activeQuizId: legacy.quiz.quiz_id })
  syncActive(useSession.setState, practices, legacy.quiz.quiz_id)
  serialize({ ...useSession.getState(), activeQuizId: legacy.quiz.quiz_id, practices })
  Taro.removeStorageSync(LEGACY_STORAGE_KEY)
}
