import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { definirGestionnaireNonAuthentifie } from "../api/client";

/**
 * Enregistre, dans le contexte du routeur, le gestionnaire appelé par
 * `appelerApi` sur tout 401 (session expirée en cours d'usage, pas
 * seulement au chargement d'une route protégée — voir `client.ts`).
 * Ne rend rien : composant de câblage, placé une fois sous `<BrowserRouter>`.
 *
 * Revue finale de la refonte du front (constat DROITS-2) : la session a
 * expiré, les données en mémoire sont celles d'un compte qui n'est plus
 * connecté — le cache est vidé en même temps que la redirection vers la
 * connexion, comme à la déconnexion (`Gabarit.tsx`) et à la connexion
 * (`Connexion.tsx`).
 */
export function EcouteAuthentification(): null {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  useEffect(() => {
    definirGestionnaireNonAuthentifie(() => {
      navigate("/connexion", { replace: true });
      queryClient.clear();
    });
    return () => definirGestionnaireNonAuthentifie(null);
  }, [navigate, queryClient]);

  return null;
}
