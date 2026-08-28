import { Button, Icon, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useRef, useState } from 'react'
import PracticeRhythm from '../../components/PracticeRhythm'
import { generateReport } from '../../services/api'
import { restoreSession, useSession } from '../../store/session'
import './index.scss'

export default function ReportGeneratingPage() {
  const { setReport } = useSession()
  const quiz = useSession((state) => state.quiz)
  const [error, setError] = useState('')
  const started = useRef(false)

  async function generate() {
    const { quiz, answers } = useSession.getState()
    if (!quiz) {
      Taro.switchTab({ url: '/pages/index/index' })
      return
    }
    setError('')
    try {
      const report = await generateReport(quiz, answers)
      setReport(report)
      Taro.redirectTo({ url: '/pages/report/index' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '报告生成失败，请稍后重试')
    }
  }

  useDidShow(() => {
    restoreSession()
    if (!started.current) {
      started.current = true
      void generate()
    }
  })

  return <View className='report-generating-page'>
    <View className='generating-header'><Text className='brand-mark'>EO</Text><Text className='brand-name'>EasyOffer</Text></View>
    <View className='generating-content page-enter'>
      {error ? <>
        <View className='state-icon error'><Icon type='warn' size={34} color='#e65368' /></View>
        <Text className='state-title'>报告生成失败</Text>
        <Text className='state-copy'>{error}</Text>
        <Button className='primary-button report-retry-button' onClick={() => void generate()}>重新生成报告</Button>
        <Button className='secondary-button report-return-button' onClick={() => Taro.switchTab({ url: '/pages/index/index' })}>返回答题</Button>
      </> : <>
        <View className='state-icon'><Icon type='waiting' size={34} color='#315fdd' /></View>
        <Text className='state-title'>正在生成本轮报告</Text>
        <Text className='state-copy'>正在整理你的答题表现，提炼知识薄弱点与下一步建议</Text>
        <Text className='source-hint'>{quiz?.evidence_meta?.used_personal_kb ? '本报告参考了你的个人知识库资料' : quiz?.evidence_meta?.used_web ? '本报告参考了联网资料' : '本报告基于基础模型知识与本轮答题数据'}</Text>
        <View className='report-rhythm'><PracticeRhythm steps={['整理答题', '分析掌握', '形成建议']} currentStep={0} indeterminate summary='分析完成后将立即展示报告' /></View>
        <View className='progress-track'><View className='progress-fill' /></View>
        <Text className='state-hint'>通常需要 10-20 秒，请稍候</Text>
      </>}
    </View>
  </View>
}
