import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@contracts': fileURLToPath(
        new URL('../../packages/typescript-contracts/src', import.meta.url),
      ),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts'],
    clearMocks: true,
  },
  build: {
    sourcemap: false,
    target: 'es2023',
  },
})
