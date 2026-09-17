import { useEffect } from "react";
import { useNavigate } from "react-router";

import { definirGestionnaireNonAuthentifie } from "../api/client";

/**
 * Enregistre, dans le contexte du routeur, le gestionnaire appelé par
 * `appelerApi` sur tout 401 (session expirée en cours d'usage, pas
 * seulement au chargement d'une route protégée — voir `client.ts`).
 * Ne rend rien : composant de câblage, placé une fois sous `<BrowserRouter>`.
 */
export function EcouteAuthentification(): null {
  const navigate = useNavigate();

  useEffect(() => {
    definirGestionnaireNonAuthentifie(() => {
      navigate("/connexion", { replace: true });
    });
    return () => definirGestionnaireNonAuthentifie(null);
  }, [navigate]);

  return null;
}
