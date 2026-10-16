import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, /api calls are forwarded to the FastAPI server on port 8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://localhost:8000" } },
});
