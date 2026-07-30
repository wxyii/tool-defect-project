import type { RouteRecordRaw } from 'vue-router'

const LoginView = () => import('@/views/LoginView.vue')
const OidcCallbackView = () => import('@/views/OidcCallbackView.vue')
const PlaceholderView = () => import('@/views/PlaceholderView.vue')
const UnauthorizedView = () => import('@/views/UnauthorizedView.vue')
const WorkstationView = () => import('@/views/WorkstationView.vue')

export const applicationRoutes: readonly RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { requiresAuth: false, standalone: true },
  },
  {
    path: '/auth/callback',
    name: 'oidc-callback',
    component: OidcCallbackView,
    meta: { requiresAuth: false, standalone: true },
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
    ['/detections', 'detections', '检测记录', 'detection:read'],
    ['/reviews', 'reviews', '复核任务', 'review:read'],
    ['/quality', 'quality', '质量分析', 'quality:read'],
    ['/datasets', 'datasets', '数据集', 'dataset:read'],
    ['/training-runs', 'training-runs', '训练运行', 'training:read'],
    ['/models', 'models', '模型与部署', 'model:read'],
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
