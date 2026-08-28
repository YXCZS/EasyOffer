import { Button, View } from '@tarojs/components'

interface PageBackButtonProps {
  label?: string
  onClick: () => void
}

export default function PageBackButton({ label = '返回', onClick }: PageBackButtonProps) {
  return <Button className='page-back-button' aria-label={label} onClick={onClick}>
    <View className='back-icon' />
  </Button>
}
