import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import PracticeRhythm from '../../components/PracticeRhythm'
import { createQuizGenerationTask, getQuizGenerationTask, QuizGenerationTaskSnapshot, retryQuizGenerationTask } from '../../services/api'
import { restoreSession, useSession } from '../../store/session'
import { advanceMotionStage } from '../../utils/motion'
import './index.scss'

definePageConfig({ navigationStyle: 'custom' })

const stages = ['理解主题', '准备资料', '生成首题', '开始答题']

export default function QuizGeneratingPage() {
  const applyGenerationSnapshot = useSession((state) => state.applyGenerationSnapshot)
  const [error, setError] = useState('')
  const [stage, setStage] = useState(0)
  const [generatedCount, setGeneratedCount] = useState(0)
  const [totalCount, setTotalCount] = useState(6)
  const [sourceHint, setSourceHint] = useState('')
  const started = useRef(false)
  const taskIdRef = useRef<string | null>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollInFlight = useRef(false)
  const pollGeneration = useRef(0)
  const redirected = useRef(false)
  const autoRetryCount = useRef(0)
  const consecutiveErrors = useRef(0)

  function stopPolling() {
    pollGeneration.current += 1
    if (pollTimer.current) clearTimeout(pollTimer.current)
    pollTimer.current = null
  }

  useEffect(() => () => stopPolling(), [])

  function consume(taskId: string, snapshot: QuizGenerationTaskSnapshot) {
    taskIdRef.current = taskId
    setGeneratedCount(snapshot.generated_count)
    setTotalCount(snapshot.total_count)
    applyGenerationSnapshot(taskId, snapshot)
    if (snapshot.quiz) {
      const sources = snapshot.quiz.evidence_meta?.source_types || []
      setSourceHint(snapshot.quiz.evidence_meta?.used_base_model
        ? '当前资料较少，已使用基础模型补充生成'
        : sources.includes('personal_kb') ? '已参考你的个人知识库'
          : sources.includes('web') ? '已参考联网资料' : '使用基础模型知识生成')
    }
    const nextStage = snapshot.generated_count > 0 ? (snapshot.status === 'completed' ? 3 : 2) : snapshot.status === 'generating' ? 1 : 0
    setStage((current) => advanceMotionStage(current, nextStage, stages.length))
  }

  async function openQuiz(taskId: string) {
    // Keep the task id in the URL as a recovery hint.  The session is still
    // persisted in Zustand/storage, but the page can fetch the latest snapshot
    // if a mini-program page transition races with storage hydration.
    const url = `/pages/quiz/index?task_id=${encodeURIComponent(taskId)}`
    try {
      await Taro.redirectTo({ url })
    } catch (_) {
      // redirectTo can fail while the devtools is finishing a route animation;
      // navigateTo is a safe fallback and keeps the generated session intact.
      try {
        await Taro.navigateTo({ url })
      } catch (error) {
        setError(error instanceof Error ? error.message : '无法进入答题页面，请重试')
        redirected.current = false
      }
    }
  }

  function schedulePoll(taskId: string, delay: number, generation: number) {
    if (generation !== pollGeneration.current || redirected.current) return
    if (pollTimer.current) clearTimeout(pollTimer.current)
    pollTimer.current = setTimeout(() => { void poll(taskId, generation) }, delay)
  }

  async function poll(taskId: string, generation = pollGeneration.current): Promise<void> {
    if (generation !== pollGeneration.current || redirected.current) return
    if (pollInFlight.current) {
      schedulePoll(taskId, 8000, generation)
      return
    }
    pollInFlight.current = true
    try {
      const snapshot = await getQuizGenerationTask(taskId)
      if (snapshot.status === 'failed' && snapshot.generated_count > 0 && autoRetryCount.current < 2) {
        autoRetryCount.current += 1
        const retried = await retryQuizGenerationTask(taskId)
        consume(taskId, retried)
        schedulePoll(taskId, 6000, generation)
        return
      }
      consume(taskId, snapshot)
      if (snapshot.status === 'failed' || snapshot.status === 'expired') {
        stopPolling()
        setError(snapshot.error_message || '题目生成失败，请稍后重试')
        return
      }
      if (snapshot.generated_count >= 1 && snapshot.questions.length >= 1 && !redirected.current) {
        redirected.current = true
        setStage((current) => advanceMotionStage(current, snapshot.status === 'completed' ? 3 : 2, stages.length))
        stopPolling()
        void openQuiz(taskId)
        return
      }
      consecutiveErrors.current = 0
      const delay = snapshot.generated_count === 0 ? 2500 : 6000
      schedulePoll(taskId, delay, generation)
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务状态查询失败，请重试')
      consecutiveErrors.current += 1
      const delay = Math.min(10000, 3000 * (2 ** Math.min(consecutiveErrors.current - 1, 2)))
      schedulePoll(taskId, delay, generation)
    } finally {
      pollInFlight.current = false
    }
  }

  async function generate() {
    const { topic, role, difficulty, documentId, generateImages, usePersonalKnowledge } = useSession.getState()
    if (!topic.trim()) {
      Taro.switchTab({ url: '/pages/index/index' })
      return
    }
    stopPolling()
    pollGeneration.current += 1
    autoRetryCount.current = 0
    consecutiveErrors.current = 0
    redirected.current = false
    setError('')
    setStage(0)
    setGeneratedCount(0)
    try {
      const initial = await createQuizGenerationTask(topic.trim(), role, difficulty, {
        ...(documentId ? { documentId, knowledgeOnly: true } : {}),
        generateImages,
        usePersonalKnowledge: usePersonalKnowledge || Boolean(documentId),
      })
      consume(initial.task_id, initial)
      await poll(initial.task_id, pollGeneration.current)
    } catch (err) {
      setError(err instanceof Error ? err.message : '题目生成失败，请稍后重试')
    }
  }

  async function retry() {
    const taskId = taskIdRef.current
    if (!taskId) return generate()
    try {
      setError('')
      autoRetryCount.current = 0
      redirected.current = false
      const snapshot = await retryQuizGenerationTask(taskId)
      consume(taskId, snapshot)
      stopPolling()
      await poll(taskId, pollGeneration.current)
    } catch (err) {
      setError(err instanceof Error ? err.message : '重试失败，请稍后重试')
    }
  }

  useEffect(() => {
    try {
      restoreSession()
      if (!started.current) {
        started.current = true
        void generate()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '会话恢复失败，请返回后重试')
    }
    return () => stopPolling()
  }, [])

  const topic = useSession((state) => state.topic)
  const progress = Math.round((generatedCount / Math.max(totalCount, 1)) * 100)
  return <View className='quiz-generating-page'>
    <View className='generating-topbar'><View className='generating-brand'><Text className='brand-mark'>EO</Text><Text>EasyOffer</Text></View><Text className='topbar-label'>题组准备</Text></View>
    <View className='generating-main page-enter'>
      {error ? <View className='generating-error'>
        <View className='error-symbol'>!</View>
        <Text className='generating-title'>题组生成失败</Text>
        {generatedCount > 0 && <Text className='generating-copy'>已准备 {generatedCount}/{totalCount} 道题</Text>}
        <Text className='generating-copy'>{error}</Text>
        <Button className='primary-button generating-primary' onClick={() => void retry()}>重试生成</Button>
        <Button className='secondary-button generating-secondary' onClick={() => Taro.switchTab({ url: '/pages/index/index' })}>返回修改主题</Button>
      </View> : <>
        <View className={`orbital-logo ${stage === 3 ? 'complete' : ''}`}><View className='orbital-ring ring-one' /><View className='orbital-ring ring-two' /><View className='orbital-core'><Text>AI</Text></View></View>
        <Text className='generating-title'>{stage === 3 ? '题组准备完成' : generatedCount > 0 ? '首题已准备好' : '正在生成你的题组'}</Text>
        <Text className='generating-copy'>{stage === 3 ? '马上进入答题，开始你的面试训练' : generatedCount > 0 ? `已准备 ${generatedCount}/${totalCount} 道题，后续题目将在答题时继续生成` : '正在理解主题、准备资料并生成第一道面试题'}</Text>
        {sourceHint && <Text className='generating-source'>{sourceHint}</Text>}
        <View className='topic-chip'><Text className='topic-chip-label'>练习主题</Text><Text className='topic-chip-value'>{topic}</Text></View>
        <View className='generating-rhythm'><PracticeRhythm steps={stages} currentStep={stage} completed={stage === 3} summary={generatedCount > 0 ? `已生成 ${generatedCount}/${totalCount} 道题` : '首题准备进度'} /></View>
        <View className='progress-track'><View className='progress-fill' style={{ width: `${progress}%` }} /></View>
        <Text className='generating-hint'>{generatedCount > 0 ? '正在后台准备下一题' : '通常只需等待第一道题生成'}</Text>
      </>}
    </View>
  </View>
}
