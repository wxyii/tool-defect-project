import type { RouteRecordRaw } from 'vue-router'

const LoginView = () => import('@/views/LoginView.vue')
const ChangePasswordView = () => import('@/views/ChangePasswordView.vue')
const UserManagementView = () => import('@/views/UserManagementView.vue')
const PlaceholderView = () => import('@/views/PlaceholderView.vue')
const UnauthorizedView = () => import('@/views/UnauthorizedView.vue')
const WorkstationView = () => import('@/views/WorkstationView.vue')
const DetectionListView = () => import('@/views/DetectionListView.vue')
const DetectionDetailView = () => import('@/views/DetectionDetailView.vue')
const ReviewQueueView = () => import('@/views/ReviewQueueView.vue')
const ReviewWorkbenchView = () => import('@/views/ReviewWorkbenchView.vue')
const DatasetVersionsView = () => import('@/features/datasets/DatasetVersionsView.vue')
const TrainingRunsView = () => import('@/features/training/TrainingRunsView.vue')
const ModelsView = () => import('@/features/models/ModelsView.vue')
const QualityDashboard = () => import('@/features/quality/QualityDashboard.vue')

export const applicationRoutes: readonly RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { requiresAuth: false, standalone: true },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: ChangePasswordView,
    meta: { requiresAuth: true, standalone: true },
  },
  {
    path: '/users',
    name: 'users',
    component: UserManagementView,
    meta: {
      requiresAuth: true,
      permissions: ['user:manage'],
      menuLabel: '账号管理',
      menuIcon: '◎',
    },
  },
  {
    path: '/unauthorized',
    name: 'unauthorized',
    component: UnauthorizedView,
    meta: { requiresAuth: true },
  },
  {
    path: '/workstation',
    name: 'workstation',
    component: WorkstationView,
    meta: {
      requiresAuth: true,
      permissions: ['detection:read'],
      menuLabel: '工位实时',
      menuIcon: '◉',
      workstation: true,
    },
  },
  {
    path: '/detections',
    name: 'detections',
    component: DetectionListView,
    meta: {
      requiresAuth: true,
      permissions: ['detection:read'],
      menuLabel: '检测记录',
      menuIcon: '⌁',
    },
  },
  {
    path: '/detections/:id',
    name: 'detection-detail',
    component: DetectionDetailView,
    meta: {
      requiresAuth: true,
      permissions: ['detection:read'],
    },
  },
  {
    path: '/reviews',
    name: 'reviews',
    component: ReviewQueueView,
    meta: {
      requiresAuth: true,
      permissions: ['review:read'],
      menuLabel: '复核任务',
      menuIcon: '◇',
    },
  },
  {
    path: '/reviews/:id',
    name: 'review-workbench',
    component: ReviewWorkbenchView,
    meta: {
      requiresAuth: true,
      permissions: ['review:read'],
    },
  },
  ...featureRoutes(),
  ...placeholderRoutes(),
  {
    path: '/',
    redirect: '/workstation',
    meta: { requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/workstation',
    meta: { requiresAuth: true },
  },
]

function placeholderRoutes(): RouteRecordRaw[] {
  const definitions = [
    ['/dashboard', 'dashboard', '系统总览', 'detection:read'],
    ['/devices', 'devices', '设备与工位', 'device:read'],
    ['/alerts', 'alerts', '告警', 'alert:read'],
    ['/audit', 'audit', '审计', 'audit:read'],
    ['/settings', 'settings', '受控配置', 'configuration:read'],
  ] as const
  return definitions.map(([path, name, label, permission]) => ({
    path,
    name,
    component: PlaceholderView,
    props: { title: label },
    meta: {
      requiresAuth: true,
      permissions: [permission],
      menuLabel: label,
      menuIcon: '•',
    },
  }))
}

function featureRoutes(): RouteRecordRaw[] {
  return [
    {
      path: '/datasets',
      name: 'datasets',
      component: DatasetVersionsView,
      meta: {
        requiresAuth: true,
        permissions: ['dataset:read'],
        menuLabel: '数据集',
        menuIcon: '▤',
      },
    },
    {
      path: '/training-runs',
      name: 'training-runs',
      component: TrainingRunsView,
      meta: {
        requiresAuth: true,
        permissions: ['training:read'],
        menuLabel: '训练运行',
        menuIcon: '⚙',
      },
    },
    {
      path: '/models',
      name: 'models',
      component: ModelsView,
      meta: {
        requiresAuth: true,
        permissions: ['model:read'],
        menuLabel: '模型与部署',
        menuIcon: '⬡',
      },
    },
    {
      path: '/quality',
      name: 'quality',
      component: QualityDashboard,
      meta: {
        requiresAuth: true,
        permissions: ['quality:read'],
        menuLabel: '质量分析',
        menuIcon: '◈',
      },
    },
  ]
}
