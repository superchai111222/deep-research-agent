import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL("./index.html", import.meta.url)),
        v2: fileURLToPath(new URL("./v2.html", import.meta.url))
      }
    }
  },
  server: {
    port: 5174
  }
});
