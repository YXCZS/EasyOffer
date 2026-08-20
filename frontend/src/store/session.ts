import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { AnswerRecord, Quiz, Report, Role, Difficulty } from '../types/domain'

const STORAGE_KEY = 'easyoffer-session-v1'
interface SessionState {
  topic: string
  role: Role
  difficulty: Difficulty
  quiz: Quiz | null
  currentIndex: number
  answers: AnswerRecord[]
  report: Report | null
  setTopic: (topic: string) => void
  setRole: (role: Role) => void
  setDifficulty: (difficulty: Difficulty) => void
  setQuiz: (quiz: Quiz) => void
  recordAnswer: (answer: AnswerRecord) => void
  advanceQuestion: () => void
  setReport: (report: Report) => void
  reset: () => void
}

const initial = { topic: '', role: 'general' as Role, difficulty: 'medium' as Difficulty, quiz: null, currentIndex: 0, answers: [], report: null }
function persist(state: Partial<SessionState>) {
  Taro.setStorageSync(STORAGE_KEY, { ...initial, ...state })
}

export const useSession = create<SessionState>((set, get) => ({
  ...initial,
  setTopic: (topic) => { set({ topic }); persist({ ...get(), topic }) },
  setRole: (role) => { set({ role }); persist({ ...get(), role }) },
  setDifficulty: (difficulty) => { set({ difficulty }); persist({ ...get(), difficulty }) },
  setQuiz: (quiz) => { set({ quiz, currentIndex: 0, answers: [], report: null }); persist({ ...get(), quiz, currentIndex: 0, answers: [], report: null }) },
  recordAnswer: (answer) => {
    const answers = [...get().answers.filter((item) => item.question_id !== answer.question_id), answer]
    set({ answers }); persist({ ...get(), answers })
  },
  advanceQuestion: () => {
    const currentIndex = Math.min(get().currentIndex + 1, (get().quiz?.questions.length || 1) - 1)
    set({ currentIndex }); persist({ ...get(), currentIndex })
  },
  setReport: (report) => { set({ report }); persist({ ...get(), report }) },
  reset: () => { set(initial); Taro.removeStorageSync(STORAGE_KEY) },
}))

export function restoreSession() {
  const saved = Taro.getStorageSync<Partial<SessionState>>(STORAGE_KEY)
  if (!saved) return
  useSession.setState({ ...initial, ...saved })
}
