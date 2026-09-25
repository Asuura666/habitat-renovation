import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { ErreurApi } from "./api/client";
// Polices auto-hébergées (spec §2) : la CSP (`default-src 'self'`) interdit
// Google Fonts, d'où `@fontsource/*` plutôt que les liens `<link>` des
// maquettes. Poids réellement utilisés par la charte seulement (titres
// Fraunces 500/600, texte IBM Plex Sans 400/500/600, montants et numéros
// IBM Plex Mono 500 — voir `tailwind.config.cjs`).
import "@fontsource/fraunces/500.css";
import "@fontsource/fraunces/600.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Politique centralisée (au lieu d'options divergentes par hook) :
      // jamais de nouvelle tentative sur une erreur d'autorisation (401/403,
      // ne se corrige pas en réessayant — et un 401 a déjà déclenché la
      // redirection via `EcouteAuthentification`), au plus 2 tentatives pour
      // le reste (erreur réseau, 5xx, etc.).
      retry: (nombreEchecs, erreur) => {
        if (erreur instanceof ErreurApi && (erreur.status === 401 || erreur.status === 403)) {
          return false;
        }
        return nombreEchecs < 2;
      },
      // Fraîcheur de 30 s par défaut (Task 7, audit rapidité) : le défaut
      // TanStack (`staleTime: 0`) relançait 5 à 7 requêtes par écran à
      // chaque montage et à chaque retour de focus sur la fenêtre (ex.
      // ChantiersListe : chantiers, agences, bilan, tableau de bord,
      // chantiers silencieux, dépôts par agent, réglages — souvent des
      // agrégats recalculés côté serveur pour rien). Même durée que la
      // pastille « À régler » de `Gabarit.tsx`, déjà à 30 s. La fraîcheur
      // après une écriture reste garantie par les invalidations explicites
      // de chaque mutation (`invaliderApresChangementAnomalies` et les
      // autres `invalidateQueries` ciblés) : elles forcent le refetch des
      // requêtes actives tout de suite, sans attendre ces 30 s. Les
      // `refetchInterval` déjà posés (`ARegler.tsx`, `DocumentsListe.tsx`)
      // continuent de rafraîchir à leur propre cadence, indépendante de
      // `staleTime`.
      staleTime: 30_000,
    },
  },
});

const conteneur = document.getElementById("root");
if (!conteneur) {
  throw new Error("Élément #root introuvable dans index.html");
}

createRoot(conteneur).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
