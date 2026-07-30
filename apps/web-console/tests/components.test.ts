import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DispositionStatus from '@/components/DispositionStatus.vue'
import WorkstationView from '@/views/WorkstationView.vue'

describe('工位基础布局和可访问状态', () => {
  it.each([
    ['PASS', '通过', '✓'],
    ['FAIL', '不通过', '×'],
    ['HOLD', '暂停并等待处理', '!'],
  ] as const)('%s 同时提供文字和图标', (state, label, icon) => {
    const wrapper = mount(DispositionStatus, {
      props: { disposition: state },
    })
    expect(wrapper.text()).toContain(label)
    expect(wrapper.text()).toContain(icon)
    expect(wrapper.attributes('role')).toBe('status')
  })

  it('1920 工位壳包含中心、队列、磁盘和明确 HOLD 文案', () => {
    Object.defineProperty(window, 'innerWidth', { value: 1920, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 1080, configurable: true })
    const wrapper = mount(WorkstationView)
    expect(wrapper.text()).toContain('暂停并等待处理')
    expect(wrapper.text()).toContain('本地待上传')
    expect(wrapper.text()).toContain('磁盘使用率')
    expect(wrapper.find('.workstation-grid').exists()).toBe(true)
  })
})
