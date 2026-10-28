import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// In dev, /api is proxied to the local backend. If the repo's .env has an API_TOKEN, the proxy
// attaches it server-side so you skip the login screen; the token never reaches the browser bundle.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const target = env.API_URL || 'http://localhost:8000'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          headers: env.API_TOKEN ? { Authorization: `Bearer ${env.API_TOKEN}` } : {},
        },
      },
    },
  }
})
