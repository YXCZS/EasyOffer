import { Button, Icon, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useState } from 'react'
import { generateReport } from '../../services/api'
import { restoreSession, useSession } from '../../store/session'
import './index.scss'

export default function QuizPage() {
  const { quiz, currentIndex, recordAnswer, advanceQuestion, setReport } = useSession()
  const [selected, setSelected] = useState<string[]>([])
  const [feedback, setFeedback] = useState(false)
  const [startedAt] = useState(Date.now())
  useDidShow(() => restoreSession())
  if (!quiz) return <View className='empty-page'><Text>没有找到待练习题组</Text><Button onClick={() => Taro.navigateBack()}>返回首页</Button></View>
  const activeQuiz = quiz
  const question = activeQuiz.questions[currentIndex]
  const isLast = currentIndex === activeQuiz.questions.length - 1
  function choose(key: string) { if (feedback) return; setSelected(question.type === 'multiple' ? selected.includes(key) ? selected.filter((x) => x !== key) : [...selected, key] : [key]) }
  async function submit() {
    if (!selected.length) return
    recordAnswer({ question_id: question.id, selected_answers: selected, duration_ms: Date.now() - startedAt }); setFeedback(true)
  }
  async function next() {
    if (!isLast) {
      advanceQuestion()
      setSelected([])
      setFeedback(false)
      return
    }
    const report = await generateReport(activeQuiz, useSession.getState().answers)
    setReport(report)
    Taro.redirectTo({ url: '/pages/report/index' })
  }
  const correct = selected.length === question.answer.length && selected.every((item) => question.answer.includes(item))
  return <View className='quiz-page'>
    <View className='status-row'><Text>09:43</Text><Text>5G 91%</Text></View>
    <View className='quiz-bar'><Button className='icon-button' aria-label='返回首页' onClick={() => Taro.navigateBack()}><View className='back-icon' /></Button><Text>{String(currentIndex + 1).padStart(2, '0')} / 06</Text><Text className='timer'>02:18</Text></View>
    {feedback && <View className={`result-banner ${correct ? 'success' : 'danger'}`}><View className='result-icon'><Icon type={correct ? 'success' : 'warn'} size={24} color={correct ? '#0d9b7a' : '#e65368'} /></View><View><Text className='result-title'>{correct ? '回答正确' : '这道题答错了'}</Text><Text className='result-copy'>你的答案：{selected.join('、')} {correct ? '' : `· 正确答案：${question.answer.join('、')}`}</Text></View></View>}
    <View className='quiz-content'>
      <View className='tags'><Text className='tag blue'>Redis</Text><Text className='tag orange'>{question.difficulty === 'medium' ? '中等' : question.difficulty}</Text><Text className='tag'>单{question.type === 'multiple' ? '多' : ''}选题</Text></View>
      <Text className='question-type'>Q{String(currentIndex + 1).padStart(2, '0')} / {question.knowledge_point}</Text><Text className='question-title'>{question.stem}</Text>
      <View className='options'>{question.options.map((option) => <Button key={option.key} className={`option ${selected.includes(option.key) ? 'selected' : ''}`} onClick={() => choose(option.key)}><Text className='option-letter'>{option.key}</Text><Text>{option.text}</Text></Button>)}</View>
      {feedback && <View className={`explanation ${correct ? '' : 'wrong'}`}><Text className='explanation-title'>{correct ? '核心结论' : '高风险误区'}</Text><Text>{question.explanation}</Text><Text className='explanation-misconception'>{question.misconception}</Text></View>}
    </View>
    <View className='quiz-action'><Button className='primary-button' disabled={!selected.length && !feedback} onClick={feedback ? next : submit}>{feedback ? isLast ? '查看本轮报告' : <><Text>下一题</Text><View className='chevron-icon' /></> : '提交答案'}</Button></View>
  </View>
}
