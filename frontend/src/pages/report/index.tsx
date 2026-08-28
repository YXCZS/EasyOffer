import { Button, Icon, Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'
import PageBackButton from '../../components/PageBackButton'
import PracticeRhythm from '../../components/PracticeRhythm'
import { useSession } from '../../store/session'
import { buildQuestionResults } from '../../utils/quiz-answers'
import './index.scss'

export default function ReportPage() {
  const { report, quiz, answers, reset } = useSession()
  const [brokenImages, setBrokenImages] = useState<Record<string, boolean>>({})
  if (!report) {
    return <View className='empty-page'><Text>暂无本轮报告</Text><Button onClick={() => Taro.switchTab({ url: '/pages/index/index' })}>返回答题</Button></View>
  }

  const knowledgeRows = [
    ...report.mastered_points.map((item) => [item, '92', 'good']),
    ...report.review_points.map((item) => [item, '48', 'review']),
  ]
  const questionResults = report.question_results?.length ? report.question_results : buildQuestionResults(quiz, answers)

  return <View className='report-page page-enter'>
    <View className='report-bar'>
      <PageBackButton label='返回答题' onClick={() => Taro.switchTab({ url: '/pages/index/index' })} />
      <Text>本轮复盘</Text>
      <View className='report-mark'><Icon type='success' size={18} color='#0d9b7a' /></View>
    </View>
    <View className='report-hero'>
      <View className='score-row content-enter'><View className='score'><Text>{report.score}</Text><Text>/ {report.total}</Text></View><View className='score-copy'><Text>本轮复盘完成</Text><Text>重点修正待巩固知识点</Text></View></View>
      <View className='report-rhythm-summary content-enter content-enter-delay-1'><PracticeRhythm compact completed steps={['完成答题', '分析表现', '形成报告']} currentStep={2} summary='本轮练习路径' /></View>
      <View className='result-stats content-enter content-enter-delay-2'><View className='result-stat correct'><Text>回答正确</Text><Text className='stat-number'>{report.score}</Text><Text>已掌握知识点</Text></View><View className='result-stat review'><Text>待巩固</Text><Text className='stat-number'>{report.total - report.score}</Text><Text>建议继续复习</Text></View></View>
    </View>
    <View className='report-content'>
      <View className='report-section'><Text className='section-title'>知识点表现</Text>{knowledgeRows.map(([label, value, type]) => <View className='knowledge-row' key={label}><Text>{label}</Text><View className='mini-bar'><View className={`mini-fill ${type}`} style={{ width: `${value}%` }} /></View><Text>{value}</Text></View>)}</View>
      <View className='report-section question-results'><Text className='section-title'>逐题答题情况</Text>{questionResults.length ? questionResults.map((item) => { const visualization = quiz?.questions.find((question) => question.id === item.question_id)?.visualization; return <View className={`question-result ${item.status}`} key={item.question_id}>
        <View className='question-result-heading'><View className='question-result-index'><Text>第{item.question_number}题</Text><Text className='question-result-point'>{item.knowledge_point}</Text></View><Text className='question-result-status'>{item.status === 'correct' ? '回答正确' : item.status === 'incorrect' ? '回答错误' : '未作答'}</Text></View>
        <Text className='question-result-stem'>{item.stem}</Text>
        <View className='answer-line'><Text className='answer-label'>你的答案</Text><Text className='answer-value'>{item.selected_answer_texts.length ? item.selected_answer_texts.join('；') : item.selected_answers.length ? item.selected_answers.join('、') : '未作答'}</Text></View>
        {item.status !== 'correct' && <View className='answer-line'><Text className='answer-label correct-label'>正确答案</Text><Text className='answer-value'>{item.correct_answer_texts.join('；')}</Text></View>}
        <Text className='question-result-explanation'>{item.explanation}</Text>
        {visualization?.status === 'ready' && visualization.image_url && !brokenImages[item.question_id] && <View className='question-result-visual'><Text className='question-result-visual-title'>知识点配图</Text><Image className='question-result-image' src={visualization.image_url} mode='aspectFit' onError={() => setBrokenImages((current) => ({ ...current, [item.question_id]: true }))} /><Text className='question-result-visual-alt'>{visualization.alt_text || '技术示意图'}</Text></View>}
      </View> }) : <Text className='question-results-empty'>本轮报告暂无逐题明细</Text>}</View>
      <View className='report-section'><Text className='section-title'>三句知识总结</Text>{report.summary.map((item, index) => <Text className='list-item' key={item}><Text className='list-number'>{String(index + 1).padStart(2, '0')}</Text>{item}</Text>)}</View>
      <View className='report-section'><Text className='section-title'>下一步建议</Text>{report.advice.map((item) => <Text className='list-item' key={item}><Text className='list-dot'>/</Text>{item}</Text>)}</View>
      <Text className='limit'>{report.limitations}</Text>
      <View className='report-actions'><Button className='primary-button' onClick={() => { reset(); Taro.reLaunch({ url: '/pages/index/index' }) }}>再练一轮</Button></View>
    </View>
  </View>
}
