import 'vue-router'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth: boolean
    standalone?: boolean
    permissions?: readonly string[]
    anyPermissions?: readonly string[]
    menuLabel?: string
    menuIcon?: string
    workstation?: boolean
  }
}
