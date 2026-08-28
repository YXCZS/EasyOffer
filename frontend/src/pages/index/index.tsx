import { Button, Image, Switch, Text, Textarea, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useState } from 'react'
import { useSession, restoreSession } from '../../store/session'
import { useAuth } from '../../store/auth'
import { abandonQuizProgress, ApiRequestError, getIncompleteQuizzes, IncompleteQuizItem } from '../../services/api'
import { Difficulty, Role } from '../../types/domain'
import './index.scss'

const roleOptions: Array<[Role, string]> = [
  ['general', '通用基础'], ['backend', '后端开发'], ['frontend', '前端开发'],
  ['ai', 'AI / 大模型'], ['data-algorithm', '数据 / 算法'], ['testing-devops', '测试 / 运维'],
  ['mobile', '移动端'], ['security', '安全工程'],
]
const difficultyOptions: Array<[Difficulty, string]> = [['easy', '基础'], ['medium', '中等'], ['hard', '进阶']]
const roleLabels: Record<Role, string> = {
  general: '通用基础', 'java-backend': '后端开发', backend: '后端开发', frontend: '前端开发',
  ai: 'AI / 大模型', 'data-algorithm': '数据 / 算法', 'testing-devops': '测试 / 运维', mobile: '移动端', security: '安全工程',
}
const difficultyLabels: Record<Difficulty, string> = { easy: '基础', medium: '中等', hard: '进阶' }

export default function Index() {
  const { topic, role, difficulty, generateImages, usePersonalKnowledge, setTopic, setRole, setDifficulty, setGenerateImages, setUsePersonalKnowledge, setDocumentContext, restorePractice, removePractice } = useSession()
  const { user, isGuest, refresh } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [incomplete, setIncomplete] = useState<IncompleteQuizItem[]>([])
  const [deletingQuizId, setDeletingQuizId] = useState<string | null>(null)

  async function loadIncomplete() {
    const authState = useAuth.getState()
    const sessionState = useSession.getState()
    if (authState.isGuest) {
      const localItems = Object.values(sessionState.practices)
        .filter((item) => item.status === 'in_progress' || item.status === 'ready_for_report')
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .map((item) => ({
          quiz_id: item.quiz.quiz_id,
          title: item.quiz.title,
          topic: item.quiz.topic,
          role: item.quiz.role,
          difficulty: item.quiz.difficulty,
          status: item.status as 'in_progress' | 'ready_for_report',
          answered_count: item.answers.length,
          total_questions: item.quiz.questions.length,
          current_index: item.currentIndex,
          updated_at: new Date(item.updatedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
        }))
      setIncomplete(localItems)
      return
    }
    try {
      const result = await getIncompleteQuizzes()
      setIncomplete(result.items)
    } catch (_) {
      setIncomplete([])
    }
  }

  useDidShow(() => {
    restoreSession()
    void refresh().finally(() => { void loadIncomplete() })
  })

  async function openIncomplete(item: IncompleteQuizItem) {
    try {
      await restorePractice(item.quiz_id)
      await Taro.navigateTo({ url: item.status === 'ready_for_report' ? '/pages/report-generating/index' : '/pages/quiz/index' })
    } catch (err) {
      Taro.showToast({ title: err instanceof Error ? err.message : '练习恢复失败，请重试', icon: 'none' })
    }
  }

  async function removeIncomplete(item: IncompleteQuizItem) {
    if (deletingQuizId) return
    const modal = await Taro.showModal({
      title: '删除未完成练习',
      content: `确定不再继续“${item.title || item.topic}”吗？`,
      confirmText: '删除',
      cancelText: '保留',
    })
    if (!modal.confirm) return
    setDeletingQuizId(item.quiz_id)
    try {
      if (isGuest) {
        removePractice(item.quiz_id)
      } else {
        await abandonQuizProgress(item.quiz_id)
      }
      setIncomplete((current) => current.filter((candidate) => candidate.quiz_id !== item.quiz_id))
      await loadIncomplete()
    } catch (err) {
      if (err instanceof ApiRequestError && err.statusCode === 404) {
        setIncomplete((current) => current.filter((candidate) => candidate.quiz_id !== item.quiz_id))
        await loadIncomplete()
        return
      }
      Taro.showToast({ title: err instanceof Error ? err.message : '删除失败，请稍后重试', icon: 'none' })
    } finally {
      setDeletingQuizId(null)
    }
  }

  async function handleGenerate() {
    if (topic.trim().length < 2 || topic.trim().length > 2000) { setError('请输入 2-2000 字的技术面试知识点'); return }
    setDocumentContext(null, null)
    setError(''); setLoading(true)
    try {
      await Taro.navigateTo({ url: '/pages/quiz-generating/index' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法进入题目生成页面，请重试')
    } finally {
      setLoading(false)
    }
  }

  return <View className='page-shell page-enter'>
    <View className='app-bar greeting-bar'>
      <View className='greeting-main' onClick={() => Taro.switchTab({ url: '/pages/profile/index' })}>
        <View className='home-avatar'>
          {user?.avatar_url ? <Image className='home-avatar-image' src={user.avatar_url} mode='aspectFill' /> : <Text>{user?.nickname?.slice(0, 1) || 'E'}</Text>}
        </View>
        <View className='greeting-copy'>
          <Text className='greeting-title'>你好，{user?.nickname || '学习者'}</Text>
          <Text className='greeting-subtitle'>准备好开始今天的练习了吗？</Text>
        </View>
      </View>
      <View className='header-actions'>
        <View className='xp-badge'><Text className='xp-value'>{user?.total_xp || 0}</Text><Text className='xp-label'>XP</Text></View>
        <Button className='history-button' aria-label='练习记录' onClick={() => isGuest ? Taro.switchTab({ url: '/pages/profile/index' }) : Taro.navigateTo({ url: '/pages/history/index' })}><View className='history-icon' /></Button>
      </View>
    </View>
    <View className='screen-content'>
      {incomplete.length > 0 && <View className='incomplete-section content-enter'>
        <View className='incomplete-heading'><Text className='section-kicker'>未完成练习</Text><Text className='incomplete-count'>{incomplete.length} 组</Text></View>
        {incomplete.map((item, index) => <View className='incomplete-card' style={{ animationDelay: `${Math.min(index, 4) * 55}ms` }} key={item.quiz_id} onClick={() => void openIncomplete(item)}>
          <View className='incomplete-card-main'><Text className='incomplete-title'>{item.title || item.topic}</Text><Text className='incomplete-meta'>{roleLabels[item.role]} · {difficultyLabels[item.difficulty]} · {item.updated_at}</Text></View>
          <View className='incomplete-card-side'><Text className='incomplete-progress'>{item.answered_count}/{item.total_questions}</Text><Text className='incomplete-action'>{item.status === 'ready_for_report' ? '生成报告' : '继续答题'} <Text className='incomplete-arrow'>›</Text></Text><Button className='incomplete-delete' disabled={deletingQuizId === item.quiz_id} onClick={(event) => { event.stopPropagation(); void removeIncomplete(item) }}>{deletingQuizId === item.quiz_id ? '删除中' : '删除'}</Button></View>
        </View>)}
      </View>}
      <View className='home-intro content-enter'><Text className='screen-title'>今天想攻克哪个面试知识点？</Text>
      <Text className='screen-subtitle'>输入一个技术主题，生成一组由浅入深的 6 道题。</Text></View>
      <View className='field-block content-enter content-enter-delay-1'><View className='field-label'><Text>练习主题</Text><Text>2-2000 字</Text></View>
        <Textarea className='topic-input' value={topic} maxlength={2000} placeholder='例如：Redis 持久化机制，重点考察 RDB 与 AOF 的区别' onInput={(event) => setTopic(event.detail.value)} />
      </View>
      <View className={`settings-panel ${settingsOpen ? 'expanded' : ''}`}>
        <Button className='settings-toggle' onClick={() => setSettingsOpen((open) => !open)}>
          <View className='settings-toggle-copy'><Text className='settings-title'>出题设置</Text><Text className='settings-summary'>{roleLabels[role]} · {difficultyLabels[difficulty]}</Text></View>
          <View className='settings-chevron' />
        </Button>
        {settingsOpen && <View className='settings-content content-enter'>
          <View className='control-row'><View className='field-label'><Text>岗位方向</Text></View><View className='segmented role-segmented'>{roleOptions.map(([value, label]) => <Button key={value} className={`segment ${role === value ? 'active' : ''}`} onClick={() => setRole(value)}>{label}</Button>)}</View></View>
          <View className='control-row'><View className='field-label'><Text>练习难度</Text></View><View className='segmented'>{difficultyOptions.map(([value, label]) => <Button key={value} className={`segment ${difficulty === value ? 'active' : ''}`} onClick={() => setDifficulty(value)}>{label}</Button>)}</View><Text className='difficulty-hint'>{difficulty === 'easy' ? '概念、原理与基本用法' : difficulty === 'medium' ? '常见场景、对比与问题排查' : '系统设计、性能权衡与工程实践'}</Text></View>
          <View className='control-row image-toggle-row'><View className='field-label'><Text>生成图片</Text><Text className='difficulty-hint'>为适合可视化的解析生成配图</Text></View><Switch checked={generateImages} color='#2563eb' onChange={(event) => setGenerateImages(Boolean(event.detail.value))} /></View>
          <View className='control-row image-toggle-row'><View className='field-label'><Text>使用个人知识库</Text><Text className='difficulty-hint'>{isGuest ? '登录后可使用' : '仅检索自己上传的文档'}</Text></View><Switch disabled={isGuest} checked={usePersonalKnowledge} color='#2563eb' onChange={(event) => setUsePersonalKnowledge(Boolean(event.detail.value))} /></View>
        </View>}
      </View>
      {error && <Text className='error-text status-enter'>{error}</Text>}
      <Button className='primary-button home-generate-button content-enter content-enter-delay-3' disabled={loading} onClick={handleGenerate}><Text className='ai-mark'>AI</Text><Text>{loading ? '正在进入...' : '生成 6 道题'}</Text></Button>
      <Text className='helper-line'>通常需要 10-20 秒，登录后可随时继续未完成练习</Text>
    </View>
  </View>
}
