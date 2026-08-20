export type Role = 'general' | 'java-backend' | 'frontend'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type QuestionType = 'single' | 'multiple' | 'judge'

export interface Option { key: string; text: string }
export interface Question {
  id: string
  type: QuestionType
  stem: string
  options: Option[]
  answer: string[]
  explanation: string
  option_explanations: Record<string, string>
  knowledge_point: string
  misconception: string
  difficulty: Difficulty
  version_context: string
}
export interface Quiz {
  quiz_id: string
  title: string
  summary: string
  topic: string
  role: Role
  difficulty: Difficulty
  questions: Question[]
  model_version: string
  prompt_version: string
}
export interface AnswerRecord {
  question_id: string
  selected_answers: string[]
  duration_ms: number
}
export interface Report {
  quiz_id: string
  topic: string
  score: number
  total: number
  accuracy: number
  mastered_points: string[]
  review_points: string[]
  summary: string[]
  advice: string[]
  limitations: string
}
