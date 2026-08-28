export type Role = 'general' | 'java-backend' | 'backend' | 'frontend' | 'ai' | 'data-algorithm' | 'testing-devops' | 'mobile' | 'security'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type QuestionType = 'single' | 'multiple' | 'judge'
export type ResearchTool = 'tavily_search' | 'tavily_extract'
export type VisualizationStatus = 'none' | 'pending' | 'ready' | 'failed'
export type VisualizationType = 'conceptual' | 'flowchart' | 'sequence' | 'er' | 'mindmap' | 'state'

export interface Option { key: string; text: string }
export interface QuestionVisualization {
  enabled: boolean
  mode?: 'image' | null
  type?: VisualizationType | null
  image_prompt?: string | null
  alt_text?: string | null
  asset_id?: string | null
  image_url?: string | null
  status?: VisualizationStatus
}
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
  visualization?: QuestionVisualization | null
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
  research_used?: boolean
  research_mode?: 'agent' | 'none'
  research_tools?: ResearchTool[]
  research_fallback_reason?: string | null
  sources?: QuizSource[]
  retrieved_at?: string | null
  evidence_meta?: {
    route?: string
    document_id?: string
    knowledge_only?: boolean
    evidence_count?: number
    used_base_model?: boolean
    route_reasons?: string[]
    source_types?: string[]
    used_personal_kb?: boolean
    used_web?: boolean
    confidence?: 'high' | 'medium' | 'low' | 'none' | string
    coverage?: number
    conflict?: boolean
    tool_calls?: string[]
    elapsed_ms?: number
    fallback_reason?: string | null
  }
  generate_images?: boolean
}
export interface QuizSource {
  source_id: string
  title: string
  url: string
  site: string
  excerpt: string
  retrieved_at: string
}
export interface AnswerRecord {
  question_id: string
  selected_answers: string[]
  duration_ms: number
}
export interface QuestionResult {
  question_id: string
  question_number: number
  stem: string
  knowledge_point: string
  status: 'correct' | 'incorrect' | 'unanswered'
  selected_answers: string[]
  selected_answer_texts: string[]
  correct_answers: string[]
  correct_answer_texts: string[]
  duration_ms: number
  explanation: string
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
  /** Optional for reports saved before per-question details were added. */
  question_results?: QuestionResult[]
}
