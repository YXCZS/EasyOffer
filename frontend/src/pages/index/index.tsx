import { Button, Icon, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useState } from 'react'
import { generateQuiz } from '../../services/api'
import { useSession, restoreSession } from '../../store/session'
import { Difficulty, Role } from '../../types/domain'
import './index.scss'

const examples = ['Java 线程池', '浏览器渲染', 'MySQL 索引']
const roleOptions: Array<[Role, string]> = [['general', '通用基础'], ['java-backend', 'Java 后端'], ['frontend', '前端']]
const difficultyOptions: Array<[Difficulty, string]> = [['easy', '基础'], ['medium', '中等'], ['hard', '进阶']]

export default function Index() {
  const { topic, role, difficulty, setTopic, setRole, setDifficulty, setQuiz } = useSession()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  useDidShow(() => restoreSession())

  async function handleGenerate() {
    if (topic.trim().length < 2 || topic.trim().length > 2000) { setError('请输入 2-2000 字的技术面试知识点'); return }
    setError(''); setLoading(true)
    try {
      const quiz = await generateQuiz(topic.trim(), role, difficulty)
      setQuiz(quiz)
      Taro.navigateTo({ url: '/pages/quiz/index' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '题组生成失败，请稍后重试')
    } finally { setLoading(false) }
  }

  return <View className='page-shell'>
    <View className='status-row'><Text>09:41</Text><Text>5G 92%</Text></View>
    <View className='app-bar brand-bar'><View className='brand'><Text className='brand-mark'>EO</Text><Text>EasyOffer</Text></View><View className='history-button' aria-label='练习记录'><View className='history-icon' /></View></View>
    <View className='screen-content'>
      <Text className='eyebrow'>AI TECH INTERVIEW</Text>
      <Text className='screen-title'>今天想攻克哪个{`\n`}面试知识点？</Text>
      <Text className='screen-subtitle'>输入一个技术主题，生成一组由浅入深的 6 道题。</Text>
      <View className='field-block'><View className='field-label'><Text>练习主题</Text><Text>2-2000 字</Text></View>
        <Textarea className='topic-input' value={topic} maxlength={2000} placeholder='例如：Redis 持久化机制，重点考察 RDB 与 AOF 的区别' onInput={(event) => setTopic(event.detail.value)} />
        <View className='suggestions'>{examples.map((example) => <Button key={example} className='suggestion' onClick={() => setTopic(example === 'Java 线程池' ? 'Java 线程池核心参数与拒绝策略' : example === '浏览器渲染' ? '浏览器从输入 URL 到页面渲染的完整过程' : 'MySQL 索引失效的常见场景')}>{example}</Button>)}</View>
      </View>
      <View className='control-row'><View className='field-label'><Text>目标岗位</Text></View><View className='segmented'>{roleOptions.map(([value, label]) => <Button key={value} className={`segment ${role === value ? 'active' : ''}`} onClick={() => setRole(value)}>{label}</Button>)}</View></View>
      <View className='control-row'><View className='field-label'><Text>练习难度</Text></View><View className='segmented'>{difficultyOptions.map(([value, label]) => <Button key={value} className={`segment ${difficulty === value ? 'active' : ''}`} onClick={() => setDifficulty(value)}>{label}</Button>)}</View></View>
      {error && <Text className='error-text'>{error}</Text>}
      <Button className={`primary-button ${loading ? 'loading' : ''}`} disabled={loading} onClick={handleGenerate}>{loading ? <><Icon type='waiting' size={18} color='#ffffff' /> <Text>正在生成题组</Text></> : <><Text className='ai-mark'>AI</Text><Text>生成 6 道题</Text></>}</Button>
      <Text className='helper-line'>{loading ? '正在组织题目与讲解，完成后自动进入第 1 题' : '通常需要 10-20 秒，本轮记录仅保存在当前设备'}</Text>
    </View>
  </View>
}
