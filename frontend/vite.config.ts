import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'SERVER_')
  return {
    plugins: [react()],
    server: {
      port: 5174, strictPort: true,
      proxy: { '/api': { target: env.SERVER_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
    },
  }
})
