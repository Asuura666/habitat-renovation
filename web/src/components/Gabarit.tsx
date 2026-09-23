import { type ReactElement, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router";

import { CLE_COMPTE_A_REGLER, obtenirCompteARegler, problemes } from "../api/aTraiter";
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
  /** Libellé de la barre de navigation basse (téléphone, < `md`), quand il
   * diffère de celui de la barre latérale (ordinateur) — Task 6, seule
   * tâche autorisée à modifier ce fichier : « Vue d'ensemble » déborde à
   * 375 px dans la barre basse, remplacé là par « Accueil » ; la barre
   * latérale garde « Vue d'ensemble » (`libelle` ci-dessus, jamais
   * modifié). `undefined` réutilise `libelle` tel quel. */
  libelleCourt?: string;
  Icone: IconeNav;
}

/** Cinq entrées de la navigation admin (spec §3) : « Vue d'ensemble » = `/`,
 * « À régler » (remplace « À traiter »/« Anomalies »), « Chantiers »
 * (remplace « Bilan »), « Fournisseurs », « Documents » (remplace
 * « Factures »/« BL déposés »). Pastille du nombre de problèmes à régler
 * sur « À régler » posée au rendu (voir `PastilleARegler` ci-dessous), pas
 * dans cette table statique. */
const NAV_ADMIN: EntreeNav[] = [
  { vers: "/", libelle: "Vue d'ensemble", libelleCourt: "Accueil", Icone: IconeVueEnsemble },
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

/** Liens discrets Réglages/Journal : l'entrée active se distingue par la
 * graisse, la couleur d'accent et un fond (barre latérale) ou un
 * soulignement (en-tête téléphone) — revue finale, constat TELEPHONE-14 :
 * rien n'indiquait où l'on se trouvait sur ces deux écrans. */
function classesLienDiscret({ isActive }: { isActive: boolean }): string {
  const base = "block min-h-[44px] rounded-lg px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return isActive ? `${base} bg-fond font-semibold text-accent` : `${base} hover:bg-fond`;
}

function classesLienEnTete({ isActive }: { isActive: boolean }): string {
  const base = "flex min-h-[44px] items-center border-b-2 outline-none focus-visible:ring-2 focus-visible:ring-accent";
  return isActive ? `${base} border-accent font-semibold text-accent` : `${base} border-transparent`;
}

/** Libellé en toutes lettres de la pastille « À régler » (revue finale,
 * constats LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2) : elle compte
 * **tous** les problèmes à régler, tous mois confondus — le même nombre que
 * l'en-tête de l'écran « À régler » et que le « … en tout » de la vue
 * d'ensemble (`GET /api/a-regler/compte`, compte unique calculé par le
 * serveur). Avant ce correctif, elle comptait les seuls urgents : trois
 * nombres différents (tuile du mois, pastille, écran « À régler ») se
 * lisaient sur le même parcours. */
function libellePastilleARegler(compte: number): string {
  return `${problemes(compte)} à régler en tout`;
}

/** Pastille du nombre de problèmes à régler sur l'entrée « À régler »
 * (Task 6, exception à la règle Gabarit ; compte unique depuis la revue
 * finale). Toujours doublée d'un libellé en toutes lettres (spec §2 :
 * jamais la couleur seule). `undefined` (requête pas encore résolue) ou `0`
 * n'affiche rien. */
function PastilleARegler({ compte }: { compte: number | undefined }): ReactElement | null {
  if (compte === undefined || compte === 0) {
    return null;
  }
  return (
    <span
      aria-label={libellePastilleARegler(compte)}
      title={libellePastilleARegler(compte)}
      className="inline-flex min-w-[20px] shrink-0 items-center justify-center rounded-full bg-alerte px-1.5 py-0.5 text-xs font-semibold text-white"
    >
      {compte}
    </span>
  );
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
    onSuccess: () => {
      // Revue finale (constat DROITS-2) : le cache est entièrement vidé,
      // plus seulement `["moi"]` invalidé — sur un navigateur partagé, la
      // personne qui se connecte ensuite ne doit jamais voir, même un
      // instant, les chiffres restés en mémoire de la précédente.
      navigate("/connexion", { replace: true });
      queryClient.clear();
    },
  });

  // Revue finale (constat TELEPHONE-1) : changer d'écran repart du haut de
  // la page — sans cela, un écran déjà en cache s'ouvrait à la position de
  // défilement du précédent (au téléphone : titre et chiffres hors de
  // l'écran). Seul le chemin compte : changer un filtre (`?filtre=`,
  // `?mois=`) ne fait pas sauter la page ; une ancre (`#…`) est laissée à
  // l'écran qui la cible.
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (hash === "") {
      window.scrollTo(0, 0);
    }
    // `hash` volontairement absent : seul un changement d'écran remonte.
  }, [pathname]);

  // La page d'un bon (`/bl/:id`) appartient à « Documents » (revue finale,
  // constat LIENS-8) : sans cela, aucune entrée n'était active sur cette
  // page, pourtant ouverte depuis Documents, la fiche chantier et « À
  // régler ».
  const surPageBon = useMatch("/bl/*") !== null;

  const estAdmin = moi?.role === "admin";
  const entrees = estAdmin ? NAV_ADMIN : NAV_AGENT;

  function activeAussiSurPageBon(
    vers: string,
    classes: (etat: { isActive: boolean }) => string,
  ): (etat: { isActive: boolean }) => string {
    return ({ isActive }) => classes({ isActive: isActive || (vers === "/documents" && surPageBon) });
  }

  // Pastille « À régler » (Task 6, exception à la règle Gabarit) : compte
  // unique du serveur (revue finale), jamais chargé pour un agent (qui n'a
  // pas l'entrée « À régler »). Même clé que la vue d'ensemble et l'écran
  // « À régler » : un seul appel, un seul nombre à l'écran. Invalidé par
  // toute écriture qui change des problèmes (`invaliderApresChangement
  // Anomalies`). `PastilleARegler` gère elle-même le cas `undefined`
  // (requête pas encore résolue) et `0` (rien affiché).
  const compte = useQuery({
    queryKey: CLE_COMPTE_A_REGLER,
    queryFn: obtenirCompteARegler,
    enabled: estAdmin,
    staleTime: 30_000,
  });
  const compteARegler = estAdmin ? compte.data?.nb_problemes : undefined;

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
                <NavLink
                  to={vers}
                  end={vers === "/"}
                  className={activeAussiSurPageBon(vers, classesLienBarreLaterale)}
                >
                  <Icone className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{libelle}</span>
                  {vers === "/a-regler" && <PastilleARegler compte={compteARegler} />}
                </NavLink>
                {/* Revue finale (constats LIENS-7, ECRAN-17, COUVERTURE-21) :
                    plus de sous-lien « Gérer les chantiers » — la création
                    de chantier est reprise par l'écran « Chantiers » et la
                    validation d'alias par « À régler » ; le lien menait à
                    `/chantiers/referentiel`, une simple redirection vers
                    « Chantiers » (doublon sans effet). La redirection reste
                    pour les anciens favoris (`App.tsx`). */}
              </li>
            ))}
          </ul>

          {estAdmin && (
            <ul className="mt-auto flex flex-col gap-1 text-sm text-encre-2">
              <li>
                <NavLink to="/reglages" className={classesLienDiscret}>
                  Réglages
                </NavLink>
              </li>
              <li>
                <NavLink to="/journal" className={classesLienDiscret}>
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

      {/* `min-w-0` (décision d'intégration de la refonte, revue finale,
          constat COUVERTURE-21) : sans lui, une colonne flexible ne
          rétrécit pas sous la largeur de son contenu — un tableau large
          débordait entre 768 et ~1100 px au lieu de défiler dans sa carte. */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
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
                <NavLink to="/reglages" className={classesLienEnTete}>
                  Réglages
                </NavLink>
                <NavLink to="/journal" className={classesLienEnTete}>
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
          {entrees.map(({ vers, libelle, libelleCourt, Icone }) => (
            <NavLink
              key={vers}
              to={vers}
              end={vers === "/"}
              className={activeAussiSurPageBon(vers, classesLienBarreBasse)}
            >
              <span className="relative">
                <Icone className="h-5 w-5" />
                {vers === "/a-regler" && compteARegler !== undefined && compteARegler > 0 && (
                  <span
                    aria-label={libellePastilleARegler(compteARegler)}
                    title={libellePastilleARegler(compteARegler)}
                    className="absolute -right-1.5 -top-1.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-alerte px-1 text-[10px] font-semibold text-white"
                  >
                    {compteARegler}
                  </span>
                )}
              </span>
              {/* « Accueil » plutôt que « Vue d'ensemble » ici (Task 6) :
                  ce dernier déborde à 375 px dans la barre basse — la barre
                  latérale (ci-dessus) garde le libellé complet. */}
              <span className="whitespace-nowrap text-[11px] leading-none">{libelleCourt ?? libelle}</span>
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
