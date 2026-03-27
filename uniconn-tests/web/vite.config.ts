import { defineConfig } from 'vite';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  resolve: {
    alias: {
      '@uniconn/core': resolve(__dirname, '../../uniconn-js/core/src'),
      '@uniconn/web': resolve(__dirname, '../../uniconn-js/web/src'),
    }
  }
});
