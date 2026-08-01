import type { RouteMeta } from 'vue-router'

export type PermissionCheck = (permission: string) => boolean

/**
 * 路由可同时声明全部必需权限和任一可选权限。
 *
 * `permissions` 保留原有“全部满足”语义；`anyPermissions` 用于只读页面，
 * 与后端 `hasAnyAuthority` 的鉴权规则保持一致。
 */
export function hasRouteAccess(
  meta: RouteMeta | undefined,
  hasPermission: PermissionCheck,
): boolean {
  const required = meta?.permissions ?? []
  if (!required.every((permission) => hasPermission(permission))) return false

  const alternatives = meta?.anyPermissions ?? []
  return alternatives.length === 0
    || alternatives.some((permission) => hasPermission(permission))
}
