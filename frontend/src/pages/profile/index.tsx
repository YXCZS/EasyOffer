import { Button, Canvas, Image, Input, Slider, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import { getProfile, uploadAvatar, updateProfile, UserProfile } from '../../services/api'
import { useAuth } from '../../store/auth'
import './index.scss'

const STAGE_SIZE = 280
const CROP_SIZE = 240
const FRAME_INSET = (STAGE_SIZE - CROP_SIZE) / 2
type ImageInfo = { path: string; width: number; height: number }
type Transform = { left: number; top: number; scale: number }

const MAX_ZOOM_FACTOR = 4

function point(touch: any) {
  return {
    x: touch?.clientX ?? touch?.pageX ?? touch?.x ?? 0,
    y: touch?.clientY ?? touch?.pageY ?? touch?.y ?? 0,
  }
}

function distance(first: any, second: any) {
  const firstPoint = point(first)
  const secondPoint = point(second)
  return Math.sqrt((firstPoint.x - secondPoint.x) ** 2 + (firstPoint.y - secondPoint.y) ** 2)
}

export default function ProfilePage() {
  const { user, isGuest, isLoading, error: authError, login, logout, setUser } = useAuth()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState('')
  const [savingNickname, setSavingNickname] = useState(false)
  const [imageInfo, setImageInfo] = useState<ImageInfo | null>(null)
  const [transform, setTransform] = useState<Transform | null>(null)
  const [initialTransform, setInitialTransform] = useState<Transform | null>(null)
  const [editorVisible, setEditorVisible] = useState(false)
  const [savingAvatar, setSavingAvatar] = useState(false)
  const profileRequestId = useRef(0)
  const gesture = useRef<{ mode: 'drag' | 'pinch' | ''; startX: number; startY: number; startLeft: number; startTop: number; startDistance: number; startScale: number }>({ mode: '', startX: 0, startY: 0, startLeft: 0, startTop: 0, startDistance: 0, startScale: 1 })

  useDidShow(() => {
    const requestId = ++profileRequestId.current
    if (isGuest) {
      setProfile(null)
      return
    }
    const userId = user?.id
    getProfile().then((next) => {
      const auth = useAuth.getState()
      if (requestId === profileRequestId.current && !auth.isGuest && auth.user?.id === userId) setProfile(next)
    }).catch((err) => {
      const auth = useAuth.getState()
      if (requestId === profileRequestId.current && !auth.isGuest && auth.user?.id === userId) {
        setError(err instanceof Error ? err.message : '档案加载失败')
      }
    })
  })

  useEffect(() => {
    if (isGuest) {
      profileRequestId.current += 1
      setProfile(null)
      setEditing(false)
      setNickname('')
      setEditorVisible(false)
      setError('')
    }
  }, [isGuest])

  useEffect(() => () => { gesture.current.mode = '' }, [])

  async function handleLogin() {
    setError('')
    const success = await login()
    if (success) {
      const next = await getProfile()
      setProfile(next)
    } else setError('')
  }

  function handleLogout() {
    profileRequestId.current += 1
    setProfile(null)
    setEditing(false)
    setNickname('')
    setEditorVisible(false)
    setError('')
    logout()
  }

  async function openAvatarEditor(path: string) {
    const info = await Taro.getImageInfo({ src: path })
    // Fit the complete source image inside the editor canvas first. Users can then
    // zoom in with the slider or a two-finger gesture when they want to fill the crop.
    const scale = Math.min(STAGE_SIZE / info.width, STAGE_SIZE / info.height)
    const nextInfo = { path, width: info.width, height: info.height }
    const nextTransform = { scale, left: (STAGE_SIZE - info.width * scale) / 2, top: (STAGE_SIZE - info.height * scale) / 2 }
    setImageInfo(nextInfo)
    setInitialTransform(nextTransform)
    setTransform(nextTransform)
    setEditorVisible(true)
  }

  async function chooseAvatar() {
    if (isGuest) {
      Taro.showToast({ title: '请先登录后更换头像', icon: 'none' })
      return
    }
    try {
      const result = await Taro.chooseImage({ count: 1, sizeType: ['compressed'], sourceType: ['album', 'camera'] })
      await openAvatarEditor(result.tempFilePaths[0])
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      if (!message.toLowerCase().includes('cancel')) setError('读取图片失败，请重新选择')
    }
  }

  async function handleChooseAvatar(event: any) {
    const path = event?.detail?.avatarUrl
    if (!path) {
      setError('未获取到头像，请重新选择')
      return
    }
    try {
      setError('')
      await openAvatarEditor(path)
    } catch (_) {
      setError('读取头像失败，请重新选择')
    }
  }

  function clamp(next: Transform): Transform {
    if (!imageInfo) return next
    const minimumScale = Math.min(STAGE_SIZE / imageInfo.width, STAGE_SIZE / imageInfo.height)
    const scale = Math.min(minimumScale * MAX_ZOOM_FACTOR, Math.max(minimumScale, next.scale))
    const width = imageInfo.width * scale
    const height = imageInfo.height * scale
    const leftMin = width >= CROP_SIZE ? FRAME_INSET + CROP_SIZE - width : FRAME_INSET
    const leftMax = width >= CROP_SIZE ? FRAME_INSET : FRAME_INSET + CROP_SIZE - width
    const topMin = height >= CROP_SIZE ? FRAME_INSET + CROP_SIZE - height : FRAME_INSET
    const topMax = height >= CROP_SIZE ? FRAME_INSET : FRAME_INSET + CROP_SIZE - height
    return {
      scale,
      left: Math.min(leftMax, Math.max(leftMin, next.left)),
      top: Math.min(topMax, Math.max(topMin, next.top)),
    }
  }

  function minimumScale() {
    return imageInfo ? Math.min(STAGE_SIZE / imageInfo.width, STAGE_SIZE / imageInfo.height) : 1
  }

  function setZoomRatio(ratio: number) {
    setTransform((current) => {
      if (!current) return current
      const nextScale = minimumScale() * Math.min(MAX_ZOOM_FACTOR, Math.max(1, ratio))
      const center = STAGE_SIZE / 2
      return clamp({
        scale: nextScale,
        left: center + (current.left - center) * (nextScale / current.scale),
        top: center + (current.top - center) * (nextScale / current.scale),
      })
    })
  }

  function handleTouchStart(event: any) {
    const touches = event.touches || []
    if (!transform) return
    if (touches.length >= 2) {
      gesture.current = { ...gesture.current, mode: 'pinch', startDistance: distance(touches[0], touches[1]), startScale: transform.scale }
    } else if (touches.length === 1) {
      const start = point(touches[0])
      gesture.current = { ...gesture.current, mode: 'drag', startX: start.x, startY: start.y, startLeft: transform.left, startTop: transform.top }
    }
  }

  function handleTouchMove(event: any) {
    const touches = event.touches || []
    const current = transform
    if (!current || !imageInfo) return
    if (touches.length >= 2 && gesture.current.mode !== 'pinch') {
      gesture.current = { ...gesture.current, mode: 'pinch', startDistance: distance(touches[0], touches[1]), startScale: current.scale }
      return
    }
    if (gesture.current.mode === 'pinch' && touches.length >= 2) {
      const ratio = distance(touches[0], touches[1]) / Math.max(gesture.current.startDistance, 1)
      const scale = Math.min(minimumScale() * MAX_ZOOM_FACTOR, Math.max(minimumScale(), gesture.current.startScale * ratio))
      const center = STAGE_SIZE / 2
      setTransform(clamp({ scale, left: center + (current.left - center) * (scale / current.scale), top: center + (current.top - center) * (scale / current.scale) }))
    } else if (gesture.current.mode === 'drag' && touches.length === 1) {
      const next = point(touches[0])
      setTransform(clamp({ ...current, left: gesture.current.startLeft + next.x - gesture.current.startX, top: gesture.current.startTop + next.y - gesture.current.startY }))
    }
  }

  function handleTouchEnd() {
    gesture.current.mode = ''
  }

  function resetCrop() {
    if (initialTransform) setTransform(initialTransform)
  }

  async function exportCrop() {
    if (!imageInfo || !transform) throw new Error('裁剪状态已失效')
    const context = Taro.createCanvasContext('avatarCropCanvas')
    context.clearRect(0, 0, CROP_SIZE, CROP_SIZE)
    context.setFillStyle('#ffffff')
    context.fillRect(0, 0, CROP_SIZE, CROP_SIZE)
    context.drawImage(
      imageInfo.path,
      transform.left - FRAME_INSET,
      transform.top - FRAME_INSET,
      imageInfo.width * transform.scale,
      imageInfo.height * transform.scale,
    )
    await new Promise<void>((resolve) => context.draw(false, () => resolve()))
    return new Promise<string>((resolve, reject) => {
      Taro.canvasToTempFilePath({ canvasId: 'avatarCropCanvas', x: 0, y: 0, width: CROP_SIZE, height: CROP_SIZE, destWidth: CROP_SIZE * 2, destHeight: CROP_SIZE * 2, fileType: 'jpg', quality: 0.9, success: (result) => resolve(result.tempFilePath), fail: reject })
    })
  }

  async function saveAvatar() {
    setSavingAvatar(true)
    setError('')
    try {
      const croppedPath = await exportCrop()
      const next = await uploadAvatar(croppedPath)
      setProfile(next)
      setUser(next)
      setEditorVisible(false)
      Taro.showToast({ title: '头像已更新', icon: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '头像保存失败，请重试')
    } finally {
      setSavingAvatar(false)
    }
  }

  function beginNicknameEdit() {
    setNickname(current?.nickname || '')
    setEditing(true)
    setError('')
  }

  function cancelNicknameEdit() {
    setNickname(current?.nickname || '')
    setEditing(false)
    setError('')
  }

  async function saveNickname() {
    const nextNickname = nickname.trim()
    if (!nextNickname) {
      setError('昵称不能为空')
      return
    }
    setSavingNickname(true)
    setError('')
    try {
      const updated = await updateProfile({ nickname: nextNickname })
      setProfile(updated)
      setUser(updated)
      setEditing(false)
      Taro.showToast({ title: '昵称已更新', icon: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : '昵称保存失败，请重试')
    } finally {
      setSavingNickname(false)
    }
  }

  const current = profile || user
  return <View className='user-page page-enter'>
    <View className='user-header content-enter'>
      <Button className='avatar-trigger' aria-label='更换头像' openType={isGuest ? undefined : 'chooseAvatar'} onClick={isGuest ? chooseAvatar : undefined} onChooseAvatar={handleChooseAvatar}><View className='avatar'>{current?.avatar_url ? <Image className='avatar-image' src={current.avatar_url} mode='aspectFill' /> : <Text>{current?.nickname?.slice(0, 1) || 'E'}</Text>}<View className='avatar-edit-mark'>+</View></View></Button>
      <View className='user-intro'>
        {editing ? <View className='nickname-editor'><Input className='nickname-input' value={nickname} maxlength={100} onInput={(event) => setNickname(event.detail.value)} placeholder='输入新昵称' /><View className='nickname-actions'><Button className='nickname-cancel' disabled={savingNickname} onClick={cancelNicknameEdit}>取消</Button><Button className='nickname-save' disabled={savingNickname} onClick={() => void saveNickname()}>{savingNickname ? '保存中' : '保存'}</Button></View></View> : <View className='user-name-row'><Text className='user-name'>{current?.nickname || '学习者'}</Text>{!isGuest && <Button className='edit-button' aria-label='修改昵称' onClick={beginNicknameEdit}>修改</Button>}</View>}
        <Text className='user-xp'>{current?.total_xp || 0}<Text> XP</Text></Text>
      </View>
    </View>
    {(error || authError) && <Text className='user-error'>{error || authError}</Text>}
    {isGuest && <View className='login-panel content-enter content-enter-delay-1'><Text>登录后可保存闯关记录，并在不同设备继续复习。</Text><Button className='primary-button' disabled={isLoading} onClick={handleLogin}>{isLoading ? '登录中...' : '微信登录并同步记录'}</Button></View>}
    <View className='stats-grid content-enter content-enter-delay-1'>
      <View className='stat-card'><Text className='stat-value'>{profile?.quiz_count || 0}</Text><Text className='stat-label'>完成闯关</Text></View>
      <View className='stat-card'><Text className='stat-value'>{profile?.correct_count || 0}</Text><Text className='stat-label'>答对题数</Text></View>
      <View className='stat-card'><Text className='stat-value'>{Math.round(profile?.average_accuracy || 0)}%</Text><Text className='stat-label'>平均正确率</Text></View>
    </View>
    <View className='user-menu content-enter content-enter-delay-2'>
      <Button className='menu-item' onClick={() => Taro.navigateTo({ url: '/pages/history/index' })}><Text>练习历史</Text><View className='menu-arrow' /></Button>
      {!isGuest && <Button className='menu-item' onClick={() => Taro.navigateTo({ url: '/pages/knowledge/index' })}><Text>我的知识库</Text><View className='menu-arrow' /></Button>}
      {!isGuest && <Button className='menu-item danger-item' onClick={handleLogout}><Text>退出登录</Text><View className='menu-arrow' /></Button>}
    </View>
    {editorVisible && imageInfo && transform && <View className='avatar-editor editor-enter'>
      <View className='editor-header'><Button className='editor-cancel' onClick={() => setEditorVisible(false)}>取消</Button><Text className='editor-title'>调整头像</Text><Button className='editor-save' disabled={savingAvatar} onClick={saveAvatar}>{savingAvatar ? '保存中' : '保存'}</Button></View>
      <Text className='editor-tip'>拖动图片调整位置，双指或滑杆缩放图片</Text>
      <View className='crop-stage' onTouchStart={handleTouchStart} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd} onTouchCancel={handleTouchEnd}>
        <Image className='crop-image' src={imageInfo.path} mode='scaleToFill' style={{ width: `${imageInfo.width * transform.scale}px`, height: `${imageInfo.height * transform.scale}px`, transform: `translate3d(${transform.left}px, ${transform.top}px, 0)` }} />
        <View className='crop-frame'><View className='crop-grid' /></View>
      </View>
      <View className='zoom-control'><Text className='zoom-mark'>−</Text><Slider className='zoom-slider' min={100} max={400} step={1} value={Math.round(transform.scale / minimumScale() * 100)} activeColor='#91b4ff' backgroundColor='#52617a' blockColor='#ffffff' blockSize={20} onChanging={(event) => setZoomRatio(Number(event.detail.value) / 100)} onChange={(event) => setZoomRatio(Number(event.detail.value) / 100)} /><Text className='zoom-mark'>+</Text></View>
      <Button className='reset-crop' onClick={resetCrop}>重置位置</Button>
      <Canvas className='crop-canvas' canvasId='avatarCropCanvas' width={`${CROP_SIZE}`} height={`${CROP_SIZE}`} />
    </View>}
  </View>
}
