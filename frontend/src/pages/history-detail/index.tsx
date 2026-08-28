import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useState } from 'react'
import PageBackButton from '../../components/PageBackButton'
import { getHistoryDetail, HistoryDetail } from '../../services/api'
import { useSession } from '../../store/session'
import { buildQuestionReviewRows } from '../../utils/quiz-answers'
import './index.scss'

export default function HistoryDetailPage() {
  const router = useRouter()
  const { setReport } = useSession()
  const [detail, setDetail] = useState<HistoryDetail | null>(null)
  const [error, setError] = useState('')
  const [brokenImages, setBrokenImages] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const quizId = router.params.quiz_id
    if (!quizId) { setError('缺少闯关记录编号'); return }
    getHistoryDetail(quizId).then(setDetail).catch((err) => setError(err instanceof Error ? err.message : '详情加载失败'))
  }, [router.params.quiz_id])

  const heading = <View className='detail-heading'><PageBackButton onClick={() => Taro.navigateBack()} /><Text className='detail-title'>{detail?.quiz.title || '练习详情'}</Text></View>
  if (error) return <View className='detail-page page-enter'>{heading}<Text className='detail-error status-enter'>{error}</Text></View>
  if (!detail) return <View className='detail-page page-enter'>{heading}<View className='detail-loading status-enter'><Text>正在加载历史报告...</Text></View></View>
  const report = detail.report
  const questionResults = buildQuestionReviewRows(detail.quiz, detail.answer_records)
  const resultById = new Map(questionResults.map((item) => [item.question_id, item]))
  return <View className='detail-page page-enter'>
    {heading}
    {report ? <View className='detail-content content-enter'>
      <View className='detail-score'><Text className='score-number'>{report.score}</Text><Text className='score-total'>/ {report.total}</Text><Text className='score-accuracy'>正确率 {Math.round(report.accuracy)}%</Text></View>
      <Text className='detail-summary'>{report.summary[0]}</Text>
      <View className='detail-section'><Text className='section-title'>待巩固知识点</Text>{report.review_points.length ? report.review_points.map((item) => <Text className='point' key={item}>{item}</Text>) : <Text className='muted'>本轮没有待巩固知识点</Text>}</View>
      <View className='detail-section'><Text className='section-title'>逐题答题情况</Text>{detail.quiz.questions.map((question) => { const visual = question.visualization; const result = resultById.get(question.id); return <View className={`history-question ${result?.status || 'unanswered'}`} key={question.id}><View className='history-question-meta'><Text className='history-question-type'>{result?.question_type_label || '单选题'}</Text><Text className='history-question-status'>{result?.status === 'correct' ? '回答正确' : result?.status === 'incorrect' ? '回答错误' : '未作答'}</Text></View><Text className='history-question-title'>{question.stem}</Text><View className='history-answer-row'><Text className='history-answer-label'>你的答案</Text><Text>{result?.selected_answer_texts.length ? result.selected_answer_texts.join('；') : '未作答'}</Text></View><View className='history-answer-row'><Text className='history-answer-label correct'>正确答案</Text><Text>{result?.correct_answer_texts.join('；')}</Text></View><Text className='history-question-explanation'>{question.explanation}</Text>{visual?.status === 'ready' && visual.image_url && !brokenImages[question.id] && <Image className='history-visualization-image' src={visual.image_url} mode='aspectFit' onError={() => setBrokenImages((current) => ({ ...current, [question.id]: true }))} />}</View> })}</View>
      <Button className='primary-button' onClick={() => { setReport(report); Taro.redirectTo({ url: '/pages/report/index' }) }}>查看完整报告</Button>
    </View> : <Text className='muted status-enter'>这次闯关还没有报告。</Text>}
  </View>
}
