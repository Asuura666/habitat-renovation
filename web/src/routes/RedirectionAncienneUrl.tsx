import type { ReactElement } from "react";
import { Navigate, useLocation, useParams } from "react-router";

/**
 * Redirection d'une ancienne URL vers la nouvelle (spec §3, liens déjà
 * envoyés par Telegram ou mis en favori) — un seul composant pour toutes
 * les redirections plutôt qu'un par cas (fix round 1, revue). `vers` reçoit
 * les paramètres de route de l'ancienne URL et rend le nouveau chemin ;
 * `search` (filtres, ex. `?mois=...`) et `hash` (ancre, ex. `#bloc-...`) de
 * l'URL d'origine sont toujours reportés — jamais perdus (fix round 1,
 * revue : une redirection qui les ignore casse un lien profond filtré ou
 * ancré).
 */
export function RedirectionAncienneUrl({
  vers,
}: {
  vers: (params: Readonly<Partial<Record<string, string>>>) => string;
}): ReactElement {
  const params = useParams();
  const location = useLocation();
  return <Navigate to={`${vers(params)}${location.search}${location.hash}`} replace />;
}
