import { defineConfig } from '@tarojs/cli'

export default defineConfig({
  projectName: 'easyoffer',
  date: '2026-08-20',
  designWidth: 750,
  deviceRatio: { 640: 2.34, 750: 1, 828: 1.81 },
  sourceRoot: 'src',
  // H5 and WeChat builds have incompatible output layouts. Keeping them in
  // separate directories prevents an H5 build from replacing the mini-app
  // files while WeChat DevTools is watching `dist/`.
  outputRoot: process.env.TARO_ENV === 'h5' ? 'h5-dist' : 'dist',
  framework: 'react',
  compiler: 'webpack5',
  mini: { postcss: { pxtransform: { enable: true }, cssModules: { enable: false } } },
  h5: {},
})
