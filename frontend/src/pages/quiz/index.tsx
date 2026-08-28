import { Button, Icon, Image, Text, View } from '@tarojs/components'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import PageBackButton from '../../components/PageBackButton'
import PracticeRhythm from '../../components/PracticeRhythm'
import { getQuizGenerationTask, QuizGenerationTaskSnapshot, retryQuizGenerationTask } from '../../services/api'
import { restoreSession, useSession } from '../../store/session'
import { motionDirection, MotionDirection } from '../../utils/motion'
import { canSubmitAnswer, isAnswerCorrect, questionTypeLabel, updateSelectedAnswers } from '../../utils/quiz-answers'
import { clampQuizViewIndex, nextReviewViewIndex, previousQuizViewIndex, syncQuizViewIndex } from './navigation'
import './index.scss'

definePageConfig({ navigationStyle: 'custom' })

export default function QuizPage() {
  const router = useRouter()
  const routeTaskId = router?.params?.task_id
  const { quiz, currentIndex, answers, activeQuizId, recordAnswer, advanceQuestion, saveActiveProgress, generationTaskId, generationStatus, applyGenerationSnapshot } = useSession()
  const [selected, setSelected] = useState<string[]>([])
  const [feedback, setFeedback] = useState(false)
  const [viewIndex, setViewIndex] = useState(currentIndex)
  const [retryingGeneration, setRetryingGeneration] = useState(false)
  const [startedAt, setStartedAt] = useState(Date.now())
  const [imageBroken, setImageBroken] = useState(false)
  const [transitionDirection, setTransitionDirection] = useState<MotionDirection>('steady')
  const [statusBarHeight] = useState(() => Taro.getWindowInfo?.()?.statusBarHeight || 20)
  const [hydrated, setHydrated] = useState(false)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollInFlight = useRef(false)
  const pollGeneration = useRef(0)
  const autoRetryCount = useRef(0)
  const previousPracticeId = useRef(activeQuizId)
  const previousFrontierIndex = useRef(currentIndex)

  function stopPolling() {
    pollGeneration.current += 1
    if (pollTimer.current) clearTimeout(pollTimer.current)
    pollTimer.current = null
  }

  function schedulePoll(taskId: string, delay: number, generation: number) {
    if (generation !== pollGeneration.current) return
    if (pollTimer.current) clearTimeout(pollTimer.current)
    pollTimer.current = setTimeout(() => { void refreshGeneration(taskId, generation) }, delay)
  }

  async function refreshGeneration(taskId: string, generation = pollGeneration.current): Promise<void> {
    if (generation !== pollGeneration.current) return
    if (pollInFlight.current) {
      schedulePoll(taskId, 8000, generation)
      return
    }
    pollInFlight.current = true
    try {
      const snapshot: QuizGenerationTaskSnapshot = await getQuizGenerationTask(taskId)
      // A partial task is recoverable: retry the unfinished question in the
      // background instead of showing the interruption screen immediately.
      if (snapshot.status === 'failed' && snapshot.generated_count > 0 && autoRetryCount.current < 2) {
        autoRetryCount.current += 1
        const retried = await retryQuizGenerationTask(taskId)
        applyGenerationSnapshot(taskId, retried)
        schedulePoll(taskId, 6000, generation)
        return
      }
      applyGenerationSnapshot(taskId, snapshot)
      const hasPendingVisuals = snapshot.questions.some((item) => item.visualization?.status === 'pending')
      if (snapshot.status === 'queued' || snapshot.status === 'generating' || hasPendingVisuals) {
        const waitingForNext = snapshot.questions.length <= useSession.getState().currentIndex + 1
        schedulePoll(taskId, waitingForNext ? 3000 : 6000, generation)
      } else stopPolling()
    } catch (_) {
      schedulePoll(taskId, 8000, generation)
    } finally {
      pollInFlight.current = false
    }
  }

  useEffect(() => () => stopPolling(), [])
  useEffect(() => {
    let cancelled = false
    const hydrate = async () => {
      try {
        restoreSession()
        // When route transition happens before storage hydration, use the task
        // id carried by the generating page to recover the first snapshot.
        const taskId = routeTaskId || useSession.getState().generationTaskId
        if (taskId && !useSession.getState().quiz) {
          const snapshot = await getQuizGenerationTask(taskId)
          if (!cancelled) applyGenerationSnapshot(taskId, snapshot)
        }
      } catch (_) {
        // The regular polling path will retry; keep a visible page in the
        // meantime instead of leaving the mini-program on a blank screen.
      } finally {
        if (!cancelled) setHydrated(true)
      }
    }
    void hydrate()
    return () => { cancelled = true }
  }, [routeTaskId])
  useEffect(() => {
    if (!quiz) return
    if (previousPracticeId.current !== activeQuizId) {
      setViewIndex((index) => {
        const nextIndex = clampQuizViewIndex(currentIndex, currentIndex, quiz.questions.length)
        setTransitionDirection(motionDirection(index, nextIndex))
        return nextIndex
      })
    } else {
      setViewIndex((index) => {
        const nextIndex = syncQuizViewIndex(index, previousFrontierIndex.current, currentIndex, quiz.questions.length)
        setTransitionDirection(motionDirection(index, nextIndex))
        return nextIndex
      })
    }
    previousPracticeId.current = activeQuizId
    previousFrontierIndex.current = currentIndex
  }, [activeQuizId, currentIndex, quiz?.quiz_id, quiz?.questions.length])
  const viewedQuestion = quiz?.questions[viewIndex]
  const viewedAnswer = viewedQuestion ? answers.find((item) => item.question_id === viewedQuestion.id) : undefined
  const viewedAnswerKey = viewedAnswer ? viewedAnswer.selected_answers.join(',') : ''
  useEffect(() => {
    setSelected(viewedAnswer?.selected_answers || [])
    setFeedback(Boolean(viewedAnswer))
    setStartedAt(Date.now())
    setImageBroken(false)
  }, [viewedQuestion?.id])
  useEffect(() => {
    if (!viewedAnswer) return
    setSelected(viewedAnswer.selected_answers)
    setFeedback(true)
  }, [viewedQuestion?.id, viewedAnswerKey])
  useEffect(() => {
    setImageBroken(false)
  }, [viewedQuestion?.id, viewedQuestion?.visualization?.image_url])
  useDidShow(() => {
    restoreSession()
    setHydrated(true)
    const taskId = useSession.getState().generationTaskId
    const active = useSession.getState()
    const hasPendingVisuals = Boolean(active.quiz?.questions.some((item) => item.visualization?.status === 'pending'))
    if (taskId && (active.generationStatus !== 'completed' || hasPendingVisuals)) {
      stopPolling()
      pollGeneration.current += 1
      void refreshGeneration(taskId, pollGeneration.current)
    }
  })
  useDidHide(() => { void saveActiveProgress().catch(() => undefined) })

  async function leaveQuiz() {
    try {
      await saveActiveProgress()
      await Taro.reLaunch({ url: '/pages/index/index' })
    } catch (err) {
      Taro.showToast({ title: err instanceof Error ? err.message : '进度保存失败，请重试', icon: 'none' })
    }
  }

  async function retryGeneration() {
    const taskId = useSession.getState().generationTaskId
    if (!taskId || retryingGeneration) return
    setRetryingGeneration(true)
    try {
      autoRetryCount.current = 0
      const snapshot = await retryQuizGenerationTask(taskId)
      applyGenerationSnapshot(taskId, snapshot)
      stopPolling()
      pollGeneration.current += 1
      void refreshGeneration(taskId, pollGeneration.current)
    } catch (err) {
      Taro.showToast({ title: err instanceof Error ? err.message : '重试生成失败，请稍后再试', icon: 'none' })
    } finally {
      setRetryingGeneration(false)
    }
  }

  if (!quiz && !hydrated) return <View className='quiz-page'><View className='quiz-waiting'><View className='waiting-spinner' /><Text className='waiting-title'>正在恢复答题进度</Text><Text className='waiting-copy'>请稍候，正在读取本轮题目</Text></View></View>
  if (!quiz && generationTaskId && generationStatus !== 'failed' && generationStatus !== 'expired') return <View className='quiz-page'>
    <View className='quiz-bar' style={{ paddingTop: `${statusBarHeight}px` }}>
      <PageBackButton label='返回首页并保存进度' onClick={leaveQuiz} />
      <Text className='quiz-progress'>01 / 06</Text><Text className='timer'>已答 0</Text>
    </View>
    <View className='quiz-waiting'><View className='waiting-spinner' /><Text className='waiting-title'>正在准备第一题</Text><Text className='waiting-copy'>题目生成后会自动显示，你可以稍等片刻</Text><Button className='waiting-button' onClick={() => void refreshGeneration(generationTaskId)}>立即刷新</Button></View>
  </View>
  if (!quiz) return <View className='empty-page'><Text>没有找到待练习题组</Text><Button onClick={leaveQuiz}>返回首页</Button></View>
  const activeQuiz = quiz
  const question = viewedQuestion
  const incremental = Boolean(generationTaskId)
  const waitingForQuestion = !question && incremental && generationStatus !== 'failed' && generationStatus !== 'expired'
  const isReviewing = viewIndex < currentIndex
  const isReadOnly = Boolean(viewedAnswer) || isReviewing
  const isLast = Boolean(question) && (!incremental || generationStatus === 'completed') && viewIndex === activeQuiz.questions.length - 1
  const evidenceMeta = activeQuiz.evidence_meta
  const sourceStatus = evidenceMeta?.used_web
    ? { className: 'research-used', label: '本轮已参考联网资料' }
    : evidenceMeta?.used_personal_kb
      ? { className: 'research-kb', label: '本轮已参考个人知识库' }
      : incremental && generationStatus !== 'completed'
        ? { className: 'research-pending', label: '资料来源确认中' }
        : evidenceMeta?.fallback_reason
          ? { className: 'research-basic', label: '外部资料暂不可用，已使用基础模型' }
          : { className: 'research-basic', label: '本轮使用基础模型知识' }

  function choose(key: string) {
    if (!question || feedback || isReadOnly) return
    setSelected((current) => updateSelectedAnswers(question.type, current, key))
  }

  async function submit() {
    if (!question || !canSubmitAnswer(selected, isReadOnly)) return
    recordAnswer({ question_id: question.id, selected_answers: selected, duration_ms: Date.now() - startedAt })
    setFeedback(true)
    void saveActiveProgress().catch((err) => Taro.showToast({ title: err instanceof Error ? err.message : '进度同步失败，已暂存本地', icon: 'none' }))
  }

  async function next() {
    if (!question) return
    if (isReviewing) {
      const nextIndex = nextReviewViewIndex(viewIndex, currentIndex)
      setTransitionDirection(motionDirection(viewIndex, nextIndex))
      setViewIndex(nextIndex)
      return
    }
    if (!isLast) {
      advanceQuestion()
      const nextIndex = useSession.getState().currentIndex
      setTransitionDirection(motionDirection(viewIndex, nextIndex))
      setViewIndex(nextIndex)
      setSelected([])
      setFeedback(false)
      setStartedAt(Date.now())
      setImageBroken(false)
      return
    }
    try {
      await saveActiveProgress()
      await Taro.redirectTo({ url: '/pages/report-generating/index' })
    } catch (err) {
      Taro.showToast({ title: err instanceof Error ? err.message : '进度保存失败，请重试', icon: 'none' })
    }
  }

  function previous() {
    const nextIndex = previousQuizViewIndex(viewIndex)
    setTransitionDirection(motionDirection(viewIndex, nextIndex))
    setViewIndex(nextIndex)
  }

  if (waitingForQuestion) return <View className='quiz-page'>
    <View className='quiz-bar' style={{ paddingTop: `${statusBarHeight}px` }}>
      <PageBackButton label='返回首页并保存进度' onClick={leaveQuiz} />
      <Text className='quiz-progress'>{String(viewIndex + 1).padStart(2, '0')} / 06</Text><Text className='timer'>已答 {answers.length}</Text>
    </View>
    <View className='quiz-waiting'><View className='waiting-spinner' /><Text className='waiting-title'>正在准备下一题</Text><Text className='waiting-copy'>当前答题记录已经保存，题目生成后会自动继续</Text><View className='waiting-rhythm'><PracticeRhythm compact steps={Array.from({ length: 6 }, (_, index) => `第${index + 1}题`)} currentStep={Math.min(viewIndex, 5)} summary={`已完成 ${answers.length} 道题`} /></View><Button className='waiting-button' onClick={() => generationTaskId && void refreshGeneration(generationTaskId)}>立即刷新</Button></View>
  </View>

  if (!question) return <View className='quiz-page'>
    <View className='quiz-bar' style={{ paddingTop: `${statusBarHeight}px` }}>
      <PageBackButton label='返回首页并保存进度' onClick={leaveQuiz} />
      <Text className='quiz-progress'>{String(viewIndex + 1).padStart(2, '0')} / 06</Text><Text className='timer'>已答 {answers.length}</Text>
    </View>
    <View className='quiz-waiting'>
      <View className='error-symbol'>!</View>
      <Text className='waiting-title'>{activeQuiz.questions.length > 0 ? '本轮题目生成中断' : '题目生成失败'}</Text>
      <Text className='waiting-copy'>{activeQuiz.questions.length > 0
        ? `已准备 ${activeQuiz.questions.length}/06 道题，当前题目暂未生成。你的答题记录已保存，可继续重试。`
        : '暂时没有可答题目，请重新生成。'}</Text>
      {generationStatus === 'failed' && <Button className='waiting-button' disabled={retryingGeneration} onClick={() => void retryGeneration()}>{retryingGeneration ? '正在重试...' : '继续生成题目'}</Button>}
      <Button className='waiting-button secondary' onClick={leaveQuiz}>返回首页</Button>
    </View>
  </View>
  const correct = isAnswerCorrect(selected, question.answer)
  return <View className='quiz-page'>
    <View className='quiz-bar' style={{ paddingTop: `${statusBarHeight}px` }}>
      <PageBackButton label='返回首页并保存进度' onClick={leaveQuiz} />
      <Text className='quiz-progress'>{String(viewIndex + 1).padStart(2, '0')} / {String(incremental ? 6 : activeQuiz.questions.length).padStart(2, '0')}</Text><Text className='timer'>已答 {answers.length}</Text>
    </View>
    {feedback && <View className={`result-banner status-enter ${correct ? 'success' : 'danger'}`}><View className='result-icon'><Icon type={correct ? 'success' : 'warn'} size={24} color={correct ? '#0d9b7a' : '#e65368'} /></View><View><Text className='result-title'>{correct ? '回答正确' : '这道题答错了'}</Text><Text className='result-copy'>你的答案：{selected.join('、')} {correct ? '' : ` · 正确答案：${question.answer.join('、')}`}</Text></View></View>}
    <View key={question.id} className={`quiz-content question-${transitionDirection}`}>
      <View className='quiz-rhythm'><PracticeRhythm compact steps={Array.from({ length: incremental ? 6 : activeQuiz.questions.length }, (_, index) => `第${index + 1}题`)} currentStep={viewIndex} summary={`第 ${viewIndex + 1} 题 · 共 ${incremental ? 6 : activeQuiz.questions.length} 题`} /></View>
      <View className={`research-status ${sourceStatus.className}`}><Text>{sourceStatus.label}</Text></View>
      <View className='tags'><Text className='tag blue'>{question.knowledge_point}</Text><Text className='tag orange'>{question.difficulty === 'medium' ? '中等' : question.difficulty}</Text><Text className='tag'>{questionTypeLabel(question.type)}</Text>{question.type === 'multiple' && <Text className='tag multiple-hint'>可多选</Text>}</View>
      <Text className='question-type'>Q{String(viewIndex + 1).padStart(2, '0')} / {question.knowledge_point}</Text><Text className='question-title'>{question.stem}</Text>
      <View className='options'>{question.options.map((option) => <Button key={option.key} disabled={isReadOnly} className={`option ${selected.includes(option.key) ? 'selected' : ''}`} onClick={() => choose(option.key)}><Text className='option-letter'>{option.key}</Text><Text className='option-text'>{option.text}</Text></Button>)}</View>
      {feedback && <View className={`explanation ${correct ? '' : 'wrong'}`}><Text className='explanation-title'>{correct ? '核心结论' : '高风险误区'}</Text><Text>{question.explanation}</Text><Text className='explanation-misconception'>{question.misconception}</Text>{question.visualization?.status === 'pending' && <Text className='visualization-pending'>配图生成中，文字解析不受影响</Text>}{question.visualization?.status === 'ready' && question.visualization.image_url && !imageBroken && <View className='visualization-block'><Text className='visualization-title'>知识点配图</Text><Image className='visualization-image' src={question.visualization.image_url} mode='aspectFit' onError={() => setImageBroken(true)} /><Text className='visualization-alt'>{question.visualization.alt_text || '技术示意图'}</Text></View>}</View>}
    </View>
    <View className='quiz-action'>
      <Button className='secondary-button previous-button' disabled={viewIndex <= 0} onClick={previous}>上一题</Button>
      <Button className='primary-button' disabled={!isReviewing && !feedback && !canSubmitAnswer(selected, isReadOnly)} onClick={isReviewing || feedback ? next : submit}>{isReviewing || feedback ? isLast ? '查看本轮报告' : '下一题' : '提交答案'}</Button>
    </View>
  </View>
}
