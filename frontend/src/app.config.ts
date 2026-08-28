export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/quiz-generating/index',
    'pages/quiz/index',
    'pages/report-generating/index',
    'pages/report/index',
    'pages/profile/index',
    'pages/history/index',
    'pages/history-detail/index',
    'pages/knowledge/index',
  ],
  tabBar: {
    color: '#667085',
    selectedColor: '#2563eb',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      {
        pagePath: 'pages/index/index',
        text: '答题',
        iconPath: 'assets/tab-answer.png',
        selectedIconPath: 'assets/tab-answer-active.png',
      },
      {
        pagePath: 'pages/profile/index',
        text: '我的',
        iconPath: 'assets/tab-profile.png',
        selectedIconPath: 'assets/tab-profile-active.png',
      },
    ],
  },
  window: {
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTextStyle: 'black',
    backgroundColor: '#f6f8fb',
  },
})
