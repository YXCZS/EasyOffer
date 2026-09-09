import { Button, Picker, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useState } from 'react'
import PageBackButton from '../../components/PageBackButton'
import { getHistory, HistoryItem } from '../../services/api'
import { useAuth } from '../../store/auth'
import './index.scss'

const PAGE_SIZE_OPTIONS = [10, 20, 50]

export default function HistoryPage() {
  const { isGuest } = useAuth()
  const [items, setItems] = useState<HistoryItem[]>([])
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const loadHistory = (targetPage: number, targetPageSize: number) => {
    setLoading(true)
    setError('')
    getHistory(targetPage, targetPageSize)
      .then((data) => {
        setItems(data.items)
        setPage(data.page)
        setPageSize(data.page_size)
        setTotal(data.total)
      })
      .catch((err) => setError(err instanceof Error ? err.message : '历史记录加载失败'))
      .finally(() => setLoading(false))
  }

  useDidShow(() => {
    if (isGuest) return
    loadHistory(page, pageSize)
  })

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const canPaginate = total > 0

  return <View className='history-page page-enter'>
    <View className='history-heading content-enter'><PageBackButton onClick={() => Taro.navigateBack()} /><View><Text className='eyebrow'>EASYOFFER / HISTORY</Text><Text className='page-title'>练习历史</Text></View></View>
    {isGuest && <View className='empty-state content-enter content-enter-delay-1'><Text className='empty-title'>登录后查看练习历史</Text><Text>本地游客模式只保留当前设备上的练习进度。</Text><Button className='primary-button' onClick={() => Taro.switchTab({ url: '/pages/profile/index' })}>去登录</Button></View>}
    {error && <Text className='history-error status-enter'>{error}</Text>}
    {!isGuest && !items.length && !error && <View className='empty-state content-enter content-enter-delay-1'><Text className='empty-title'>还没有完成的闯关</Text><Text>完成第一轮练习后，报告会自动出现在这里。</Text><Button className='primary-button' onClick={() => Taro.switchTab({ url: '/pages/index/index' })}>开始练习</Button></View>}
    {!isGuest && canPaginate && <View className='history-toolbar'><Text className='history-total'>共 {total} 条记录</Text><Picker mode='selector' range={PAGE_SIZE_OPTIONS.map((size) => `${size} 条/页`)} value={Math.max(0, PAGE_SIZE_OPTIONS.indexOf(pageSize))} onChange={(event) => { const nextPageSize = PAGE_SIZE_OPTIONS[Number(event.detail.value)] || PAGE_SIZE_OPTIONS[0]; setPage(1); loadHistory(1, nextPageSize) }}><View className='page-size-picker'><Text>每页 {pageSize} 条</Text><View className='picker-chevron' /></View></Picker></View>}
    <View className='history-list'>{items.map((item, index) => <Button className='history-item' style={{ animationDelay: `${Math.min(index, 6) * 45}ms` }} key={item.quiz_id} onClick={() => Taro.navigateTo({ url: `/pages/history-detail/index?quiz_id=${encodeURIComponent(item.quiz_id)}` })}><View className='history-item-main'><Text className='history-title'>{item.title}</Text><Text className='history-meta'>{item.question_count} 道题 · {item.created_at}</Text></View><Text className='history-score'>{Math.round(item.accuracy)}%</Text><View className='history-arrow' /></Button>)}</View>
    {!isGuest && canPaginate && <View className='history-pagination'><Button className='pagination-button' disabled={loading || page <= 1} onClick={() => loadHistory(page - 1, pageSize)}>上一页</Button><Text className='pagination-label'>第 {page} / {totalPages} 页</Text><Button className='pagination-button' disabled={loading || page >= totalPages} onClick={() => loadHistory(page + 1, pageSize)}>下一页</Button></View>}
  </View>
}
