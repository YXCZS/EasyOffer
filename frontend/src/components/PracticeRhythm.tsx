import { Text, View } from '@tarojs/components'
import { clampMotionStage } from '../utils/motion'
import './PracticeRhythm.scss'

interface PracticeRhythmProps {
  steps: string[]
  currentStep: number
  completed?: boolean
  compact?: boolean
  indeterminate?: boolean
  summary?: string
}

export default function PracticeRhythm({ steps, currentStep, completed = false, compact = false, indeterminate = false, summary }: PracticeRhythmProps) {
  const activeStep = clampMotionStage(currentStep, steps.length)
  return <View className={`practice-rhythm ${compact ? 'compact' : ''} ${completed ? 'completed' : ''} ${indeterminate ? 'indeterminate' : ''}`}>
    {summary && <Text className='rhythm-summary'>{summary}</Text>}
    <View className='rhythm-track'>
      {steps.map((label, index) => {
        const done = completed || index < activeStep
        const active = !completed && index === activeStep
        return <View className={`rhythm-step ${done ? 'done' : ''} ${active ? 'active' : ''}`} key={`${label}-${index}`}>
          <View className='rhythm-node'><View className='rhythm-node-core' /></View>
          {!compact && <Text className='rhythm-label'>{label}</Text>}
        </View>
      })}
    </View>
  </View>
}
