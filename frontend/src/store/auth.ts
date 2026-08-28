import Taro from '@tarojs/taro'
import { create } from 'zustand'
import { getProfile, loginWithCode } from '../services/api'
import { clearStoredAuth, getStoredAuth, setStoredAuth, UserSummary } from '../services/auth-storage'
import { useSession } from './session'

interface AuthState {
  token: string
  user: UserSummary | null
  isLoading: boolean
  isGuest: boolean
  error: string
  setUser: (user: UserSummary) => void
  restore: () => void
  login: () => Promise<boolean>
  refresh: () => Promise<void>
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  token: '',
  user: null,
  isLoading: false,
  isGuest: true,
  error: '',
  setUser: (user) => {
    const auth = getStoredAuth()
    if (auth) setStoredAuth({ token: auth.token, user })
    set({ user, isGuest: false, error: '' })
  },
  restore: () => {
    const auth = getStoredAuth()
    set({ token: auth?.token || '', user: auth?.user || null, isGuest: !auth?.token, error: '' })
  },
  login: async () => {
    set({ isLoading: true })
    try {
      const loginResult = await Taro.login()
      if (!loginResult.code) throw new Error('微信登录凭证获取失败')
      const auth = await loginWithCode(loginResult.code)
      setStoredAuth(auth)
      set({ token: auth.token, user: auth.user, isGuest: false, error: '' })
      return true
    } catch (err) {
      const message = err instanceof Error ? err.message : '微信登录失败，请稍后重试'
      set({ isGuest: true, error: message })
      return false
    } finally {
      set({ isLoading: false })
    }
  },
  refresh: async () => {
    const current = getStoredAuth()
    if (!current?.token) return
    try {
      const user = await getProfile()
      setStoredAuth({ token: current.token, user })
      set({ user, token: current.token, isGuest: false, error: '' })
    } catch (_) {
      clearStoredAuth()
      useSession.getState().clearPractices()
      set({ token: '', user: null, isGuest: true })
    }
  },
  logout: () => {
    clearStoredAuth()
    useSession.getState().clearPractices()
    set({ token: '', user: null, isGuest: true, error: '' })
  },
}))

export async function restoreAuthOnLaunch() {
  const auth = getStoredAuth()
  if (auth?.token) {
    useAuth.setState({ token: auth.token, user: auth.user, isGuest: false })
    return
  }
  await useAuth.getState().login()
}
