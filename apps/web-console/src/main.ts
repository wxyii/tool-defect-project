import { createApp } from 'vue'

import App from './App.vue'
import { restoreSession } from './auth/local-auth'
import { configureApplicationApiClient } from './api/runtime'
import { pinia } from './stores'
import { useAuthStore } from './stores/auth'
import { createApplicationRouter } from './router'
import './styles/base.css'

const app = createApp(App)
const router = createApplicationRouter(pinia)

configureApplicationApiClient(
  import.meta.env,
  window.location.origin,
  useAuthStore(pinia),
)

app.use(pinia)
app.use(router)
void restoreSession()
  .then((identity) => {
    const auth = useAuthStore(pinia)
    if (identity === null) {
      auth.clear()
    } else {
      auth.establish(identity)
    }
  })
  .catch(() => useAuthStore(pinia).clear())
  .finally(() => router.isReady().then(() => app.mount('#app')))
