import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const sourceRoot = resolve(process.cwd(), 'src')

describe('前端安全边界', () => {
  it('认证令牌和签名地址不进入浏览器持久存储', () => {
    const files = [
      'auth/memory-session.ts',
      'auth/oidc.ts',
      'stores/auth.ts',
      'api/client.ts',
      'api/ephemeral-urls.ts',
    ]
    const source = files
      .map((file) => readFileSync(resolve(sourceRoot, file), 'utf8'))
      .join('\n')
    for (const forbidden of [
      'localStorage.',
      'indexedDB.',
      'document.cookie',
    ]) {
      expect(source).not.toContain(forbidden)
    }
    expect(source).not.toMatch(/setItem\([^)]*(access|refresh)[_-]?token/i)
    expect(source).not.toMatch(/setItem\([^)]*(signed|signature|ticket)[_-]?url/i)
  })

  it('请求与推送代码不把令牌放入 URL', () => {
    const source = [
      readFileSync(resolve(sourceRoot, 'api/client.ts'), 'utf8'),
      readFileSync(resolve(sourceRoot, 'api/event-stream.ts'), 'utf8'),
    ].join('\n')
    expect(source).not.toMatch(/searchParams\.set\([^)]*token/i)
    expect(source).not.toMatch(/[?&](access_)?token=/i)
    expect(source).toContain('Authorization')
  })

  it('前端没有算法结论到最终处置的自动映射', () => {
    const files = [
      'components/DispositionStatus.vue',
      'views/WorkstationView.vue',
      'router/routes.ts',
    ]
    const source = files
      .map((file) => readFileSync(resolve(sourceRoot, file), 'utf8'))
      .join('\n')
    expect(source).not.toMatch(/QUALIFIED.{0,100}PASS/s)
    expect(source).not.toMatch(/UNQUALIFIED.{0,100}FAIL/s)
  })
})
