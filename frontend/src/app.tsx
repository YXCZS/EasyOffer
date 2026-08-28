import { Button, Text, View } from '@tarojs/components'
import type { ErrorInfo, PropsWithChildren } from 'react'
import { Component } from 'react'
import Taro, { useLaunch } from '@tarojs/taro'
import { restoreAuthOnLaunch } from './store/auth'
import './styles/global.scss'

interface ErrorBoundaryState { hasError: boolean }

class AppErrorBoundary extends Component<PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('EasyOffer page render failed', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children
    return <View className='app-error-page'>
      <Text className='app-error-title'>页面加载失败</Text>
      <Text className='app-error-copy'>请重新进入答题页面，刚才的练习进度不会丢失。</Text>
      <Button className='app-error-button' onClick={() => {
        this.setState({ hasError: false })
        void Taro.reLaunch({ url: '/pages/index/index' })
      }}>重新进入答题</Button>
    </View>
  }
}

function App({ children }: PropsWithChildren) {
  useLaunch(() => { void restoreAuthOnLaunch() })
  return <AppErrorBoundary>{children}</AppErrorBoundary>
}

export default App
