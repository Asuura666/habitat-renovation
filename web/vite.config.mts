import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy de dev uniquement : en prod, le front est servi par la même origine
// que l'API (`app/core/front.py`, L2-D16), donc aucun proxy n'est nécessaire
// en dehors de `vite dev`. Cible le port de dev standard de l'API, publié
// par `deploy/docker-compose.dev.yml` (8450) — 8460 n'a servi qu'à la
// vérification isolée en conteneur de L2-T6, jamais au flux de dev normal.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8450",
        changeOrigin: true,
      },
    },
  },
});
