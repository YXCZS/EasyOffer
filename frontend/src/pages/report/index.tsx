import { Button, Icon, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useSession } from '../../store/session'
import './index.scss'

export default function ReportPage() {
  const { report, reset } = useSession()
  if (!report) {
    return <View className='empty-page'><Text>暂无本轮报告</Text><Button onClick={() => Taro.redirectTo({ url: '/pages/index/index' })}>返回首页</Button></View>
  }

  const knowledgeRows = [
    ...report.mastered_points.map((item) => [item, '92', 'good']),
    ...report.review_points.map((item) => [item, '48', 'review']),
  ]

  return <View className='report-page'>
    <View className='status-row'><Text>09:52</Text><Text>5G 89%</Text></View>
    <View className='report-bar'>
      <Button className='icon-button' aria-label='返回首页' onClick={() => Taro.redirectTo({ url: '/pages/index/index' })}><View className='back-icon' /></Button>
      <Text>本轮复盘</Text>
      <View className='report-mark'><Icon type='success' size={18} color='#0d9b7a' /></View>
    </View>
    <View className='report-hero'>
      <View className='score-row'><View className='score'><Text>{report.score}</Text><Text>/ {report.total}</Text></View><View className='score-copy'><Text>基础已掌握</Text><Text>重点修正待巩固知识点</Text></View></View>
      <View className='result-stats'><View className='result-stat correct'><Text>回答正确</Text><Text className='stat-number'>{report.score}</Text><Text>已掌握知识点</Text></View><View className='result-stat review'><Text>待巩固</Text><Text className='stat-number'>{report.total - report.score}</Text><Text>建议继续复习</Text></View></View>
    </View>
    <View className='report-content'>
      <View className='report-section'><Text className='section-title'>知识点表现</Text>{knowledgeRows.map(([label, value, type]) => <View className='knowledge-row' key={label}><Text>{label}</Text><View className='mini-bar'><View className={`mini-fill ${type}`} style={{ width: `${value}%` }} /></View><Text>{value}</Text></View>)}</View>
      <View className='report-section'><Text className='section-title'>三句知识总结</Text>{report.summary.map((item, index) => <Text className='list-item' key={item}><Text className='list-number'>{String(index + 1).padStart(2, '0')}</Text>{item}</Text>)}</View>
      <View className='report-section'><Text className='section-title'>下一步建议</Text>{report.advice.map((item) => <Text className='list-item' key={item}><Text className='list-dot'>/</Text>{item}</Text>)}</View>
      <Text className='limit'>{report.limitations}</Text>
      <View className='report-actions'><Button className='secondary-button' onClick={() => Taro.showToast({ title: '分享功能将在增强版本开放', icon: 'none' })}>分享</Button><Button className='primary-button' onClick={() => { reset(); Taro.redirectTo({ url: '/pages/index/index' }) }}>再练一轮</Button></View>
    </View>
  </View>
}
