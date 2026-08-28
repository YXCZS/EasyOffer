import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import { deleteKnowledgeDocument, getKnowledgeDocuments, KnowledgeDocument, renameKnowledgeDocument, retryKnowledgeDocument, uploadKnowledgeDocument } from '../../services/api'
import { useAuth } from '../../store/auth'
import { useSession } from '../../store/session'
import './index.scss'

const MAX_FILE_BYTES = 20 * 1024 * 1024

function formatSize(size: number) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export default function KnowledgePage() {
  const { isGuest } = useAuth()
  const { setTopic, setRole, setDifficulty, setDocumentContext } = useSession()
  const [items, setItems] = useState<KnowledgeDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadPhase, setUploadPhase] = useState<'uploading' | 'processing'>('uploading')
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [savingNameId, setSavingNameId] = useState<string | null>(null)
  const polling = useRef<ReturnType<typeof setInterval> | null>(null)
  const loadInFlight = useRef(false)

  async function load() {
    if (isGuest || loadInFlight.current) return
    loadInFlight.current = true
    setLoading(true)
    try {
      const data = await getKnowledgeDocuments()
      setItems(data.items)
      if (data.items.some((item) => item.status === 'processing') && !polling.current) {
        polling.current = setInterval(() => { void load() }, 3000)
      } else if (!data.items.some((item) => item.status === 'processing') && polling.current) {
        clearInterval(polling.current); polling.current = null
      }
    } catch (err) { setError(err instanceof Error ? err.message : '知识库加载失败') } finally { setLoading(false); loadInFlight.current = false }
  }

  useDidShow(() => { void load() })
  useEffect(() => () => {
    if (polling.current) clearInterval(polling.current)
    polling.current = null
  }, [])

  async function chooseFile() {
    if (uploading) return
    try {
      const result = await Taro.chooseMessageFile({ count: 1, type: 'file', extension: ['pdf', 'docx', 'md', 'markdown'] })
      const file = result.tempFiles?.[0]
      if (!file?.path) return
      if (file.size && file.size > MAX_FILE_BYTES) { setError('文件不能超过 20MB'); return }
      setUploading(true); setUploadProgress(0); setUploadPhase('uploading'); setError('')
      await uploadKnowledgeDocument(file.path, file.name || '未命名文档', (progress) => {
        setUploadProgress((current) => Math.max(current, progress))
        if (progress >= 100) setUploadPhase('processing')
      })
      Taro.showToast({ title: '已加入知识库', icon: 'success' })
      await load()
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      if (!message.toLowerCase().includes('cancel')) setError(message || '文档上传失败')
    } finally { setUploading(false); setUploadProgress(0); setUploadPhase('uploading') }
  }

  async function retry(item: KnowledgeDocument) { try { await retryKnowledgeDocument(item.document_id); await load() } catch (err) { setError(err instanceof Error ? err.message : '重试失败') } }
  function beginRename(item: KnowledgeDocument) {
    setError('')
    setEditingId(item.document_id)
    setEditingName(item.original_name)
  }
  function cancelRename() {
    if (savingNameId) return
    setEditingId(null)
    setEditingName('')
  }
  async function saveRename(item: KnowledgeDocument) {
    const name = editingName.trim()
    if (!name) { setError('文档名称不能为空'); return }
    if (name.length > 255) { setError('文档名称不能超过 255 个字符'); return }
    setSavingNameId(item.document_id)
    setError('')
    try {
      const updated = await renameKnowledgeDocument(item.document_id, name)
      setItems((current) => current.map((candidate) => candidate.document_id === item.document_id
        ? { ...candidate, ...updated, original_name: updated.original_name || name }
        : candidate))
      setEditingId(null)
      setEditingName('')
      Taro.showToast({ title: '名称已保存', icon: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '名称保存失败，请稍后重试')
    } finally { setSavingNameId(null) }
  }
  function startQuiz(item: KnowledgeDocument) {
    setTopic(item.original_name)
    setRole('general')
    setDifficulty('medium')
    setDocumentContext(item.document_id, item.original_name)
    Taro.redirectTo({ url: '/pages/quiz-generating/index' })
  }
  function remove(item: KnowledgeDocument) {
    Taro.showModal({ title: '删除文档', content: `确定删除“${item.original_name}”吗？`, success: async ({ confirm }) => { if (!confirm) return; try { await deleteKnowledgeDocument(item.document_id); await load() } catch (err) { setError(err instanceof Error ? err.message : '删除失败') } } })
  }

  if (isGuest) return <View className='knowledge-page page-enter'><Text className='page-title'>我的知识库</Text><View className='empty-panel content-enter'><Text>登录后可上传自己的面试资料。</Text><Button className='primary-button' onClick={() => Taro.switchTab({ url: '/pages/profile/index' })}>去登录</Button></View></View>
  return <View className='knowledge-page page-enter'>
    <View className='page-head content-enter'><View><Text className='page-title'>我的知识库</Text><Text className='page-subtitle'>上传课程讲义、项目文档，让系统优先参考你的资料</Text></View><Button className='upload-button' disabled={uploading} onClick={chooseFile}>{uploading ? '上传中...' : '+ 上传文档'}</Button></View>
    {uploading && <View className='upload-progress-panel status-enter'><View className='upload-progress-head'><Text>{uploadPhase === 'uploading' ? '正在上传文档' : '正在解析并建立知识索引'}</Text><Text className='upload-progress-value'>{uploadProgress}%</Text></View><View className='upload-progress-track'><View className='upload-progress-fill' style={{ width: `${uploadProgress}%` }} /></View><Text className='upload-progress-hint'>{uploadPhase === 'uploading' ? '文件较大时请保持当前页面' : '上传已完成，正在处理内容，请稍候'}</Text></View>}
    {error && <Text className='error-text'>{error}</Text>}
    {loading && items.length === 0 && <Text className='loading-text'>正在加载...</Text>}
    {!loading && items.length === 0 && <View className='empty-panel'><Text className='empty-title'>还没有文档</Text><Text>支持 PDF、DOCX 和 Markdown，单个文件不超过 20MB。</Text><Button className='empty-button' onClick={chooseFile}>上传第一份资料</Button></View>}
    <View className='document-list'>{items.map((item, index) => <View className='document-card' style={{ animationDelay: `${Math.min(index, 5) * 45}ms` }} key={item.document_id}><View className='document-icon'>{item.mime_type === 'application/pdf' ? 'PDF' : 'DOC'}</View><View className='document-main'>{editingId === item.document_id ? <View className='rename-editor content-enter'><Input className='rename-input' value={editingName} maxlength={255} onInput={(event) => setEditingName(event.detail.value)} /><View className='rename-actions'><Button className='rename-save-button' disabled={savingNameId === item.document_id} onClick={() => void saveRename(item)}>{savingNameId === item.document_id ? '保存中' : '保存'}</Button><Button className='rename-cancel-button' disabled={savingNameId === item.document_id} onClick={cancelRename}>取消</Button></View></View> : <Text className='document-name'>{item.original_name}</Text>}<Text className='document-meta'>{formatSize(item.file_size)} · {item.updated_at}</Text><Text className={`document-status ${item.status}`}>{item.status === 'processing' ? '正在处理...' : item.status === 'ready' ? `已就绪 · ${item.chunk_count} 个片段` : `处理失败：${item.error_message || '未知原因'}`}</Text></View><View className='document-actions'>{editingId !== item.document_id && <Button className='rename-button' onClick={() => beginRename(item)}>编辑名称</Button>}{item.status === 'ready' && editingId !== item.document_id && <Button className='start-quiz-button' onClick={() => startQuiz(item)}>开始答题</Button>}{item.status === 'failed' && <Button onClick={() => void retry(item)}>重试</Button>}<Button className='delete-button' onClick={() => remove(item)}>删除</Button></View></View>)}</View>
  </View>
}
