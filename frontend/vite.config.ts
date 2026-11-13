import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: { local: 'index.html', central: 'central.html' } } },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
})
