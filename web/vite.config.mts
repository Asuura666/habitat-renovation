import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy de dev uniquement : en prod, le front est servi par la même origine
// que l'API (`app/core/front.py`, L2-D16), donc aucun proxy n'est nécessaire
// en dehors de `vite dev`. Cible le port de dev standard de l'API, publié
// par `deploy/docker-compose.dev.yml` (8450) — 8460 n'a servi qu'à la
// vérification isolée en conteneur de L2-T6, jamais au flux de dev normal.
const CIBLE_API_DEV = "http://127.0.0.1:8450";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: CIBLE_API_DEV,
        changeOrigin: true,
        // L2-R10 / L3-D21 : le navigateur envoie l'en-tête `Origin` du
        // serveur Vite (ex. http://127.0.0.1:5173), que `changeOrigin` ne
        // touche pas (il ne réécrit que `Host`). `ControleOrigineMiddleware`
        // (`app/core/origine.py`) compare `Origin` à l'origine du service
        // telle qu'elle est reçue et refuse alors la requête (403), alors
        // qu'elle vient bien du front servi par Vite. On réécrit `Origin`
        // vers l'origine de la cible avant l'envoi, uniquement sur cette
        // requête sortante du proxy de dev : la requête devient alors
        // indiscernable, côté contrôle serveur, d'un appel same-origin vers
        // l'API de dev. Le contrôle serveur lui-même reste strict — ce
        // fichier n'est jamais utilisé en production (front et API sur la
        // même origine, pas de proxy).
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("origin", CIBLE_API_DEV);
          });
        },
      },
    },
  },
});
