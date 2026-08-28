import Taro from '@tarojs/taro'

export const AUTH_STORAGE_KEY = 'easyoffer-auth-v1'
export const GUEST_TOKEN_STORAGE_KEY = 'easyoffer-guest-token-v1'

export interface StoredAuth {
  token: string
  user: UserSummary
}

export interface UserSummary {
  id: number
  nickname: string
  avatar_url: string
  total_xp: number
}

export function getStoredAuth(): StoredAuth | null {
  const value = Taro.getStorageSync<StoredAuth | null>(AUTH_STORAGE_KEY)
  return value?.token ? value : null
}

export function setStoredAuth(auth: StoredAuth) {
  Taro.setStorageSync(AUTH_STORAGE_KEY, auth)
}

export function clearStoredAuth() {
  Taro.removeStorageSync(AUTH_STORAGE_KEY)
}

export function getGuestToken(): string {
  const existing = Taro.getStorageSync<string>(GUEST_TOKEN_STORAGE_KEY)
  if (existing && existing.length >= 16) return existing
  const token = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
  Taro.setStorageSync(GUEST_TOKEN_STORAGE_KEY, token)
  return token
}
