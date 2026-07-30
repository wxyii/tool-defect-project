import { createApp } from 'vue'

import App from './App.vue'
import {
  configureOidcRuntime,
  createOidcRuntimeFromEnvironment,
} from './auth/runtime'
import { configureApplicationApiClient } from './api/runtime'
import { pinia } from './stores'
import { useAuthStore } from './stores/auth'
import { createApplicationRouter } from './router'
import './styles/base.css'

const app = createApp(App)
const router = createApplicationRouter(pinia)

configureOidcRuntime(
  createOidcRuntimeFromEnvironment(import.meta.env, window),
)
configureApplicationApiClient(
  import.meta.env,
  window.location.origin,
  useAuthStore(pinia),
)

app.use(pinia)
app.use(router)
void router.isReady().then(() => app.mount('#app'))
