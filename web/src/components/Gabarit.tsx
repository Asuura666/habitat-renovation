import type { ReactElement } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router";

import { appelerApi } from "../api/client";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";

type IconeNav = (props: { className: string }) => ReactElement;

function IconeVueEnsemble({ className }: { className: string }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function IconeARegler({ className }: { className: string }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <path d="M12 3.5 2.5 20h19L12 3.5Z" strokeLinejoin="round" />
      <path d="M12 10v4.5" strokeLinecap="round" />
      <circle cx="12" cy="17.3" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}

function IconeChantiers({ className }: { className: string }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <path d="M4 20V9.5l8-5 8 5V20" strokeLinejoin="round" />
      <path d="M9.5 20v-6.5h5V20" strokeLinejoin="round" />
    </svg>
  );
}

function IconeFournisseurs({ className }: { className: string }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <path d="M3.5 8.5 12 4l8.5 4.5-8.5 4.5-8.5-4.5Z" strokeLinejoin="round" />
      <path d="M3.5 8.5V16L12 20.5 20.5 16V8.5" strokeLinejoin="round" />
      <path d="M12 13v7.5" />
    </svg>
  );
}

function IconeDocuments({ className }: { className: string }): ReactElement {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className={className} aria-hidden="true">
      <path d="M6 3.5h9l3.5 3.5V20a0.5 0.5 0 0 1-0.5 0.5H6a0.5 0.5 0 0 1-0.5-0.5V4a0.5 0.5 0 0 1 0.5-0.5Z" strokeLinejoin="round" />
      <path d="M8.5 12h7M8.5 15.5h7M8.5 8.5h3" strokeLinecap="round" />
    </svg>
  );
}

interface EntreeNav {
  vers: string;
  libelle: string;
  Icone: IconeNav;
}

/** Cinq entrées de la navigation admin (spec §3) : « Vue d'ensemble » = `/`,
 * « À régler » (remplace « À traiter »/« Anomalies »), « Chantiers »
 * (remplace « Bilan »), « Fournisseurs », « Documents » (remplace
 * « Factures »/« BL déposés »). Pas de pastille de compte sur « À régler »
 * ici (décision du contrôleur : posée par la Task 6). */
const NAV_ADMIN: EntreeNav[] = [
  { vers: "/", libelle: "Vue d'ensemble", Icone: IconeVueEnsemble },
  { vers: "/a-regler", libelle: "À régler", Icone: IconeARegler },
  { vers: "/chantiers", libelle: "Chantiers", Icone: IconeChantiers },
  { vers: "/fournisseurs", libelle: "Fournisseurs", Icone: IconeFournisseurs },
  { vers: "/documents", libelle: "Documents", Icone: IconeDocuments },
];

/** Un agent terrain ne voit que ses dépôts (spec §1, hypothèse validée) :
 * seule « Documents » lui est utile, avec la déconnexion. */
const NAV_AGENT: EntreeNav[] = [{ vers: "/documents", libelle: "Documents", Icone: IconeDocuments }];

function classesLienBarreLaterale({ isActive }: { isActive: boolean }): string {
  const base =
    "flex min-h-[44px] items-center gap-3 rounded-lg px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return isActive ? `${base} bg-accent font-medium text-white` : `${base} text-encre hover:bg-fond`;
}

/** L'entrée active se distingue de plus d'une simple couleur (fix round 1,
 * revue) : une bordure haute pleine (forme, pas seulement teinte) et un
 * texte en gras s'ajoutent à la couleur d'accent. */
function classesLienBarreBasse({ isActive }: { isActive: boolean }): string {
  const base =
    "flex min-h-[44px] flex-1 flex-col items-center justify-center gap-1 border-t-2 py-2 outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return isActive
    ? `${base} border-accent font-semibold text-accent`
    : `${base} border-transparent text-encre-2`;
}

/**
 * Gabarit de l'application (Task 4, socle de la refonte du front) : barre
 * latérale fixe (≥ `md`, 232 px, charte « Registre » — maquettes
 * `Main`/`ARegler.dc.html`) ou en-tête compact + barre de navigation basse
 * (< `md`, cinq icônes), contenu de la route active (`<Outlet />`).
 * N'est monté qu'à l'intérieur de `RouteProtegee`, donc `["moi"]` est déjà
 * en cache (même clé de requête) : pas d'appel réseau supplémentaire tant
 * que les données ne sont pas jugées périmées. */
export function Gabarit(): ReactElement {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: moi } = useQuery({
    queryKey: CLE_MOI,
    queryFn: recupererMoi,
    staleTime: DUREE_CACHE_MOI,
  });

  const deconnexion = useMutation({
    mutationFn: () => appelerApi("/api/auth/logout", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_MOI });
      navigate("/connexion", { replace: true });
    },
  });

  const estAdmin = moi?.role === "admin";
  const entrees = estAdmin ? NAV_ADMIN : NAV_AGENT;

  return (
    <div className="min-h-screen bg-fond font-sans text-encre md:flex">
      {/* Barre latérale — ordinateur (>= md). `sticky top-0 h-screen` (fix
          round 1, revue) : reste visible pendant que le contenu défile
          (Réglages/Journal/déconnexion toujours atteignables sans remonter
          toute la page) ; `self-start` l'empêche de s'étirer à la hauteur
          du contenu, condition pour que `sticky` fonctionne. */}
      {moi && (
        <nav
          aria-label="Navigation principale"
          className="hidden w-[232px] shrink-0 flex-col gap-7 self-start border-r border-bordure px-5 py-7 md:sticky md:top-0 md:flex md:h-screen"
        >
          <div className="flex flex-col gap-0.5 px-1">
            <p className="font-titre text-xl font-semibold text-accent">Habitat &amp; Rénovation</p>
            <p className="text-xs text-encre-2">Contrôle des livraisons</p>
          </div>

          <ul className="flex flex-col gap-1">
            {entrees.map(({ vers, libelle, Icone }) => (
              <li key={vers}>
                <NavLink to={vers} end={vers === "/"} className={classesLienBarreLaterale}>
                  <Icone className="h-4 w-4 shrink-0" />
                  {libelle}
                </NavLink>
                {/* R1 (fix round 1) : la création de chantier et la
                    validation d'alias (`Chantiers.tsx`) restent
                    accessibles tant que la Task 7 ne les a pas reprises
                    dans la fiche chantier. */}
                {vers === "/chantiers" && (
                  <NavLink
                    to="/chantiers/referentiel"
                    className="ml-7 mt-1 block min-h-[44px] rounded-lg px-2 py-1 text-xs text-encre-2 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    Gérer les chantiers
                  </NavLink>
                )}
              </li>
            ))}
          </ul>

          {estAdmin && (
            <ul className="mt-auto flex flex-col gap-1 text-sm text-encre-2">
              <li>
                <NavLink to="/reglages" className="block min-h-[44px] rounded-lg px-3 py-2 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent">
                  Réglages
                </NavLink>
              </li>
              <li>
                <NavLink
                  to="/journal"
                  className="block min-h-[44px] rounded-lg px-3 py-2 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Journal
                </NavLink>
              </li>
            </ul>
          )}

          <div className={estAdmin ? "border-t border-bordure pt-3" : "mt-auto border-t border-bordure pt-3"}>
            <p className="truncate px-3 text-sm font-medium text-encre">{moi.nom ?? moi.email}</p>
            <button
              type="button"
              onClick={() => deconnexion.mutate()}
              disabled={deconnexion.isPending}
              className="mt-1 min-h-[44px] w-full rounded-lg px-3 py-2 text-left text-sm text-encre-2 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              Se déconnecter
            </button>
          </div>
        </nav>
      )}

      <div className="flex min-h-screen flex-1 flex-col">
        {/* En-tête compact — téléphone (< md). Deuxième rangée avec
            Réglages/Journal (fix round 1, finding 3) : la barre de
            navigation basse ne montre que les cinq entrées principales,
            ces deux écrans doivent rester atteignables au téléphone sans
            passer par l'ordinateur — vrais liens toujours visibles,
            jamais un menu qui se déplie (plus simple, pas de gestion de
            focus supplémentaire). */}
        {moi && (
          <header className="border-b border-bordure bg-surface md:hidden">
            <div className="flex items-center justify-between gap-3 px-4 py-3">
              <p className="font-titre text-base font-semibold text-accent">Habitat &amp; Rénovation</p>
              <button
                type="button"
                onClick={() => deconnexion.mutate()}
                disabled={deconnexion.isPending}
                className="min-h-[44px] rounded-lg px-3 text-sm font-medium text-encre-2 outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                Se déconnecter
              </button>
            </div>
            {estAdmin && (
              <div className="flex items-center gap-4 border-t border-bordure px-4 text-sm text-encre-2">
                <NavLink
                  to="/reglages"
                  className="flex min-h-[44px] items-center outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Réglages
                </NavLink>
                <NavLink
                  to="/journal"
                  className="flex min-h-[44px] items-center outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Journal
                </NavLink>
              </div>
            )}
          </header>
        )}

        <main className={`flex-1 px-4 py-6 sm:px-6 md:px-10 md:py-8 ${moi ? "pb-20 md:pb-8" : ""}`}>
          <Outlet />
        </main>
      </div>

      {/* Barre de navigation basse — téléphone (< md), cinq icônes + libellé */}
      {moi && (
        <nav
          aria-label="Navigation principale"
          className="fixed bottom-0 inset-x-0 z-10 flex border-t border-bordure bg-surface md:hidden"
        >
          {entrees.map(({ vers, libelle, Icone }) => (
            <NavLink key={vers} to={vers} end={vers === "/"} className={classesLienBarreBasse}>
              <Icone className="h-5 w-5" />
              <span className="text-[11px] leading-none">{libelle}</span>
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
