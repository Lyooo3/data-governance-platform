import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  publicDir: false,
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:' + (process.env.PORT || 4173),
      '/docs': 'http://127.0.0.1:' + (process.env.PORT || 4173),
      '/openapi.json': 'http://127.0.0.1:' + (process.env.PORT || 4173),
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
