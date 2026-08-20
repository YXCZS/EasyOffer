import { defineConfig } from '@tarojs/cli'

export default defineConfig({
  projectName: 'easyoffer',
  date: '2026-08-20',
  designWidth: 750,
  deviceRatio: { 640: 2.34, 750: 1, 828: 1.81 },
  sourceRoot: 'src',
  outputRoot: 'dist',
  framework: 'react',
  compiler: 'webpack5',
  mini: { postcss: { pxtransform: { enable: true }, cssModules: { enable: false } } },
  h5: {},
})
