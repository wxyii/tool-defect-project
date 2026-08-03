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
const SystemOverviewView = () => import('@/features/overview/SystemOverviewView.vue')
const AuditTrailView = () => import('@/features/audit/AuditTrailView.vue')
const ManualDetectionUploadView = () => import('@/features/manual-detection/ManualDetectionUploadView.vue')
const ManualDetectionHistoryView = () => import('@/features/manual-detection/ManualDetectionHistoryView.vue')
const ManualDetectionDetailView = () => import('@/features/manual-detection/ManualDetectionDetailView.vue')

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
    ['/devices', 'devices', '设备与工位', 'device:read'],
    ['/alerts', 'alerts', '告警', 'alert:read'],
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
      path: '/manual-detection',
      name: 'manual-detection-upload',
      component: ManualDetectionUploadView,
      meta: {
        requiresAuth: true,
        permissions: ['manual-detection:write'],
        menuLabel: '手工检测',
        menuIcon: '＋',
      },
    },
    {
      path: '/detection-batches',
      name: 'manual-detection-history',
      component: ManualDetectionHistoryView,
      meta: {
        requiresAuth: true,
        anyPermissions: ['manual-detection:read', 'manual-detection:read:all'],
        menuLabel: '批次历史',
        menuIcon: '▧',
      },
    },
    {
      path: '/detection-batches/:id',
      name: 'manual-detection-detail',
      component: ManualDetectionDetailView,
      meta: {
        requiresAuth: true,
        anyPermissions: ['manual-detection:read', 'manual-detection:read:all'],
      },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: SystemOverviewView,
      meta: {
        requiresAuth: true,
        permissions: ['detection:read'],
        menuLabel: '系统总览',
        menuIcon: '▦',
      },
    },
    {
      path: '/audit',
      name: 'audit',
      component: AuditTrailView,
      meta: {
        requiresAuth: true,
        permissions: ['audit:read'],
        menuLabel: '审计',
        menuIcon: '≡',
      },
    },
    {
      path: '/datasets',
      name: 'datasets',
      component: DatasetVersionsView,
      meta: {
        requiresAuth: true,
        anyPermissions: ['dataset:create', 'dataset:approve', 'audit:read'],
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
        anyPermissions: ['training:read', 'training:create', 'audit:read'],
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
        anyPermissions: [
          'model:register',
          'model:validate',
          'model:deploy:approve',
          'audit:read',
        ],
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
        anyPermissions: ['quality:read', 'audit:read'],
        menuLabel: '质量分析',
        menuIcon: '◈',
      },
    },
  ]
}
