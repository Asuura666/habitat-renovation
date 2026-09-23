import { type ReactElement, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import {
  type AliasEnAttente,
  type ArticleAValider,
  type ATraiter,
  CLE_A_TRAITER,
  type DocumentATraiter,
  obtenirATraiter,
} from "../api/aTraiter";
import { type Anomalie, cleAnomalies, listerAnomalies } from "../api/anomalies";
import { CLE_CHANTIERS, listerChantiers } from "../api/referentiels";
import {
  Carte,
  categorieProbleme as categorieRegle,
  EnTetePage,
  EtatVide,
  Filtres,
  type OptionFiltre,
  phraseProbleme,
  titreRegle,
  urgence,
} from "../ui";
import { formaterMontant, formaterQuantite, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";
import { ProblemeDetail } from "./ProblemeDetail";

/**
 * Écran « À régler » (Task 6, refonte du front, spec §3/§4) : file unique
 * des anomalies ouvertes et des documents/alias/articles en attente de
 * `GET /api/a-traiter`, en langage courant. Remplace `pages/Anomalies.tsx`
 * et `pages/ATraiter.tsx` (supprimés par cette tâche, tout leur contenu est
 * repris ici) — voir `App.tsx` : `/anomalies` et `/a-traiter` redirigent
 * désormais vers `/a-regler`.
 *
 * `ProblemeDetail.tsx` (panneau de droite en `lg+`, page plein écran
 * `/a-regler/:id` en dessous) importe les types et fonctions ci-dessous :
 * les deux fichiers forment un seul écran, volontairement pas séparés par
 * un troisième module partagé (rien d'autre n'en a besoin).
 */

// ---------------------------------------------------------------------------
// Modèle d'un « problème » de la liste — anomalie, ou pseudo-problème tiré
// de `GET /api/a-traiter` (document à vérifier, alias en attente, article à
// valider). `id` est un identifiant composite (`"<type>:<uuid>"`), unique
// entre les quatre origines et stable pour la route `/a-regler/:id` — les
// quatre listes ne partagent aucun espace d'identifiants garanti par l'API.
// ---------------------------------------------------------------------------

export type Urgence = "Urgent" | "À voir" | "Info";
export type CategorieFiltre = "bl" | "prix" | "quantites" | "rattacher" | "illisible" | "autre";

export type Probleme =
  | { kind: "anomalie"; id: string; anomalie: Anomalie }
  | { kind: "document"; id: string; document: DocumentATraiter }
  | { kind: "alias"; id: string; alias: AliasEnAttente }
  | { kind: "article"; id: string; article: ArticleAValider };

export function urgenceProbleme(probleme: Probleme): Urgence {
  return probleme.kind === "anomalie" ? urgence(probleme.anomalie.gravite) : "À voir";
}

export function categorieFiltreProbleme(probleme: Probleme): CategorieFiltre {
  switch (probleme.kind) {
    case "anomalie":
      return categorieRegle(probleme.anomalie.regle);
    case "document":
      return "illisible";
    case "alias":
      return "rattacher";
    case "article":
      return "autre";
  }
}

export function titreProbleme(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie":
      return titreRegle(probleme.anomalie.regle);
    case "document":
      return "Bon illisible à corriger";
    case "alias":
      return "Chantier à rattacher";
    case "article":
      return "Article à valider";
  }
}

/** Une valeur de `detail` absente ne doit jamais planter l'affichage — même
 * garde défensive que `ui/libelles.ts` (dont les fonctions équivalentes ne
 * sont pas exportées, donc pas réutilisables ici sans modifier ce fichier
 * partagé, hors périmètre de cette tâche : voir le rapport). */
export function texteOuTiret(detail: Record<string, string>, cle: string): string {
  return detail[cle] ?? "?";
}

export function montantOuTiret(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterMontant(brute);
}

export function quantiteOuTiret(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterQuantite(brute);
}

export function pointsOuTiret(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  return brute !== undefined ? `${brute} %` : "?";
}

export function pointsOuAucun(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? "aucune" : `${brute} %`;
}

const REGLES_MONTANT_HT = new Set(["R01", "R02", "R12"]);
const REGLES_MONTANT = new Set(["R05", "R13"]);
const REGLES_ECART_MONTANT = new Set(["R10", "R11"]);
const REGLES_ECART_QUANTITE = new Set(["R03", "R04"]);
const REGLES_QUANTITE = new Set(["R06", "R17"]);
const REGLES_PRIX_FACTURE = new Set(["R07", "R08"]);

/** « Montant en jeu » de la liste (maquette `ARegler`) : une seule valeur
 * déjà présente dans `detail`, mise en forme (jamais une somme, un écart ou
 * un pourcentage recalculé ici — la valeur vient telle quelle du serveur,
 * même garde que `phraseProbleme`). Un code de règle sans valeur chiffrée
 * pertinente (R09, R14, R15, R16) affiche le tiret cadratin. */
export function valeurEnJeu(anomalie: Anomalie): string {
  const { detail, regle } = anomalie;
  if (REGLES_MONTANT_HT.has(regle)) return montantOuTiret(detail, "montant_ht");
  if (REGLES_MONTANT.has(regle)) return montantOuTiret(detail, "montant");
  if (REGLES_ECART_MONTANT.has(regle)) return montantOuTiret(detail, "ecart");
  if (REGLES_ECART_QUANTITE.has(regle)) return quantiteOuTiret(detail, "ecart");
  if (REGLES_QUANTITE.has(regle)) return quantiteOuTiret(detail, "qte");
  if (REGLES_PRIX_FACTURE.has(regle)) return montantOuTiret(detail, "pu_facture");
  return TIRET;
}

export function valeurProbleme(probleme: Probleme): string {
  return probleme.kind === "anomalie" ? valeurEnJeu(probleme.anomalie) : TIRET;
}

export function phraseAffichee(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie":
      return phraseProbleme(probleme.anomalie);
    case "document": {
      const motifs = probleme.document.motifs;
      if (motifs.length === 0) {
        return "À vérifier avant traitement.";
      }
      // Résumé court sur la ligne de liste (le détail — `ProblemeDetail
      // .tsx::DetailDocument` — affiche tous les motifs, sans résumé) : au
      // delà de deux, une ligne trop longue nuit à la lisibilité de la
      // liste (démo, écran réel avec beaucoup de champs peu fiables).
      const libelles = motifs.slice(0, 2).map((motif) => libelleMotif(motif));
      const reste = motifs.length - libelles.length;
      return reste > 0 ? `${libelles.join(" · ")} — et ${reste} de plus.` : libelles.join(" · ");
    }
    case "alias":
      return `Libellé lu : « ${probleme.alias.libelle} » — ${probleme.alias.nb_documents} document${
        probleme.alias.nb_documents > 1 ? "s" : ""
      }.`;
    case "article":
      return probleme.article.libelle ?? "Unités et ratio à confirmer.";
  }
}

export function contexteProbleme(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie": {
      const a = probleme.anomalie;
      const morceaux = [a.chantier ?? TIRET, a.fournisseur ?? TIRET];
      if (a.numero_bl !== null) {
        morceaux.push(a.numero_bl);
      }
      return morceaux.join(" · ");
    }
    case "document":
      return [
        probleme.document.chantier_brut ?? TIRET,
        probleme.document.fournisseur ?? TIRET,
        probleme.document.numero ?? TIRET,
      ].join(" · ");
    case "alias":
      return probleme.alias.fournisseur;
    case "article":
      return probleme.article.fournisseur;
  }
}

export function estDejaRegle(probleme: Probleme): boolean {
  return probleme.kind === "anomalie" && probleme.anomalie.statut !== "ouverte";
}

/** Combine les anomalies ouvertes (déjà filtrées par l'appelant) et le
 * contenu de `GET /api/a-traiter` en une seule liste de problèmes —
 * composition d'affichage pure, aucune donnée recalculée. `aTraiter`
 * `undefined` (portée d'un `blocId`, voir `ARegler` ci-dessous) omet les
 * trois pseudo-problèmes : un bloc précis n'a ni document à vérifier, ni
 * alias, ni article à valider qui lui soit propre. */
function construireProblemes(anomaliesOuvertes: Anomalie[], aTraiter: ATraiter | undefined): Probleme[] {
  const problemes: Probleme[] = anomaliesOuvertes.map((anomalie) => ({
    kind: "anomalie",
    id: `anomalie:${anomalie.id}`,
    anomalie,
  }));
  if (aTraiter !== undefined) {
    for (const document of aTraiter.documents) {
      problemes.push({ kind: "document", id: `document:${document.id}`, document });
    }
    for (const alias of aTraiter.alias) {
      problemes.push({ kind: "alias", id: `alias:${alias.id}`, alias });
    }
    for (const article of aTraiter.articles) {
      problemes.push({ kind: "article", id: `article:${article.id}`, article });
    }
  }
  return problemes;
}

function compterCategorie(problemes: Probleme[], categorie: CategorieFiltre): number {
  return problemes.filter((probleme) => categorieFiltreProbleme(probleme) === categorie).length;
}

// Le maximum accepté par `GET /api/anomalies` (`_LIMITE_MAX`,
// `app/modules/api/anomalies.py`) : cet écran affiche tous les problèmes
// ouverts d'un coup, jamais paginés, donc jamais le défaut de 100 (voir
// `api/anomalies.ts::FiltresAnomalies.limite`).
const LIMITE_ANOMALIES_ECRAN = 500;

function PastilleUrgence({ urgence: valeur }: { urgence: Urgence }): ReactElement {
  const classes: Record<Urgence, string> = {
    Urgent: "bg-[#f9dedc] text-[#8c1d18]",
    "À voir": "bg-[#fbe9c6] text-[#7a4a00]",
    Info: "bg-fond text-encre-2",
  };
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${classes[valeur]}`}
    >
      {valeur}
    </span>
  );
}

function LigneProbleme({
  probleme,
  actif,
  href,
}: {
  probleme: Probleme;
  actif: boolean;
  href: string;
}): ReactElement {
  return (
    <Link
      to={href}
      className={`block min-h-[44px] px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent ${
        actif ? "bg-fond" : "hover:bg-fond"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <PastilleUrgence urgence={urgenceProbleme(probleme)} />
        <span className="whitespace-nowrap font-mono text-sm font-medium text-encre">
          {valeurProbleme(probleme)}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-encre">{titreProbleme(probleme)}</p>
      <p className="mt-0.5 text-sm text-encre">{phraseAffichee(probleme)}</p>
      <p className="mt-0.5 truncate text-xs text-encre-2">{contexteProbleme(probleme)}</p>
    </Link>
  );
}

export function ARegler(): ReactElement {
  const { id } = useParams<{ id?: string }>();
  const [parametres, setParametres] = useSearchParams();
  const navigate = useNavigate();

  const filtreActif = parametres.get("filtre") || "tous";
  // Fonctionnalité reprise de l'ancienne `Anomalies.tsx` (supprimée par
  // cette tâche, voir `App.tsx`) : `BilanFournisseur.tsx` (fiche
  // chantier/fournisseur) lie toujours vers `/anomalies?blocId=...`, qui
  // redirige maintenant vers `/a-regler` en conservant `?blocId=...`
  // (`RedirectionAncienneUrl`) — jamais recalculé, ce paramètre est relu
  // ici tel quel et transmis au serveur (`GET /api/anomalies?bloc_id=`,
  // filtre déjà existant).
  const blocId = parametres.get("blocId") || undefined;

  const filtresAnomalies = { statut: "toutes" as const, blocId, limite: LIMITE_ANOMALIES_ECRAN };
  const anomalies = useQuery({
    queryKey: cleAnomalies(filtresAnomalies),
    queryFn: () => listerAnomalies(filtresAnomalies),
  });
  // Un bloc précis n'a pas de documents/alias/articles qui lui soient
  // propres (voir `construireProblemes`) : pas d'appel réseau inutile.
  const aTraiter = useQuery({
    queryKey: CLE_A_TRAITER,
    queryFn: obtenirATraiter,
    refetchInterval: 30_000,
    enabled: blocId === undefined,
  });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });

  const chargement = anomalies.isPending || (blocId === undefined && aTraiter.isPending);
  const enErreur = anomalies.isError || (blocId === undefined && aTraiter.isError);

  const problemesOuverts = useMemo(
    () => construireProblemes((anomalies.data ?? []).filter((a) => a.statut === "ouverte"), aTraiter.data),
    [anomalies.data, aTraiter.data],
  );
  const problemesRegles = useMemo<Probleme[]>(
    () =>
      (anomalies.data ?? [])
        .filter((a) => a.statut !== "ouverte")
        .map((a) => ({ kind: "anomalie" as const, id: `anomalie:${a.id}`, anomalie: a })),
    [anomalies.data],
  );

  const nbOuverts = problemesOuverts.length;
  const nbUrgents = problemesOuverts.filter((p) => urgenceProbleme(p) === "Urgent").length;

  const options: OptionFiltre[] = [
    { valeur: "tous", libelle: "Tous", compte: nbOuverts },
    { valeur: "urgents", libelle: "Urgents", compte: nbUrgents },
    { valeur: "bl", libelle: "BL manquants", compte: compterCategorie(problemesOuverts, "bl") },
    { valeur: "prix", libelle: "Prix", compte: compterCategorie(problemesOuverts, "prix") },
    { valeur: "quantites", libelle: "Quantités", compte: compterCategorie(problemesOuverts, "quantites") },
    { valeur: "rattacher", libelle: "À rattacher", compte: compterCategorie(problemesOuverts, "rattacher") },
    { valeur: "illisibles", libelle: "Bons illisibles", compte: compterCategorie(problemesOuverts, "illisible") },
    { valeur: "regles", libelle: "Déjà réglés" },
  ];

  const listeAffichee = useMemo(() => {
    if (filtreActif === "regles") return problemesRegles;
    if (filtreActif === "urgents") return problemesOuverts.filter((p) => urgenceProbleme(p) === "Urgent");
    if (filtreActif === "tous") return problemesOuverts;
    return problemesOuverts.filter((p) => categorieFiltreProbleme(p) === (filtreActif as CategorieFiltre));
  }, [filtreActif, problemesOuverts, problemesRegles]);

  const indexActuel = id !== undefined ? listeAffichee.findIndex((p) => p.id === id) : -1;
  const problemeActuel = indexActuel >= 0 ? listeAffichee[indexActuel] : undefined;
  const idSuivant = indexActuel >= 0 && indexActuel + 1 < listeAffichee.length ? listeAffichee[indexActuel + 1]!.id : null;
  const modeDetail = id !== undefined;

  function suffixeRecherche(): string {
    const chaine = parametres.toString();
    return chaine === "" ? "" : `?${chaine}`;
  }

  function changerFiltre(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "tous") {
      suivants.delete("filtre");
    } else {
      suivants.set("filtre", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  function allerAuProblemeSuivant(): void {
    navigate(idSuivant !== null ? `/a-regler/${idSuivant}${suffixeRecherche()}` : `/a-regler${suffixeRecherche()}`);
  }

  return (
    <div className="space-y-6">
      <div className={modeDetail ? "hidden lg:block" : ""}>
        <EnTetePage
          surtitre={`${nbOuverts} problème${nbOuverts > 1 ? "s" : ""} ouvert${nbOuverts > 1 ? "s" : ""} · ${nbUrgents} urgent${
            nbUrgents > 1 ? "s" : ""
          }`}
          titre="À régler"
          actions={<Filtres options={options} valeur={filtreActif} onChange={changerFiltre} />}
        />
      </div>

      {blocId !== undefined && !modeDetail && (
        <p className="rounded-lg border border-bordure bg-surface p-3 text-sm text-encre-2">
          Problèmes de ce bon de livraison uniquement.{" "}
          <Link to="/a-regler" className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Afficher tous les problèmes
          </Link>
        </p>
      )}

      {chargement && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {enErreur && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les problèmes.
        </p>
      )}

      {!chargement && !enErreur && (
        <div className="lg:grid lg:grid-cols-5 lg:gap-5">
          <section
            aria-label="Liste des problèmes"
            className={modeDetail ? "hidden lg:col-span-3 lg:block" : "lg:col-span-3"}
          >
            <Carte className="!p-0">
              {listeAffichee.length === 0 ? (
                <div className="p-5">
                  <EtatVide message="Aucun problème pour ce filtre." />
                </div>
              ) : (
                <ul className="divide-y divide-bordure">
                  {listeAffichee.map((probleme) => (
                    <li key={probleme.id}>
                      <LigneProbleme
                        probleme={probleme}
                        actif={probleme.id === id}
                        href={`/a-regler/${probleme.id}${suffixeRecherche()}`}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </Carte>
          </section>

          <aside
            aria-label="Détail du problème sélectionné"
            className={modeDetail ? "lg:col-span-2" : "hidden lg:col-span-2 lg:block"}
          >
            {modeDetail && problemeActuel !== undefined && (
              <ProblemeDetail
                probleme={problemeActuel}
                chantiers={chantiers.data ?? []}
                lienRetour={`/a-regler${suffixeRecherche()}`}
                onTraitementReussi={allerAuProblemeSuivant}
              />
            )}
            {modeDetail && problemeActuel === undefined && (
              <Carte>
                <p className="text-sm text-encre-2">
                  Ce problème n'est plus disponible : il a peut-être déjà été traité.
                </p>
                <Link
                  to={`/a-regler${suffixeRecherche()}`}
                  className="mt-3 inline-block text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Retour à la liste
                </Link>
              </Carte>
            )}
            {!modeDetail && (
              <Carte>
                <EtatVide message="Sélectionnez un problème dans la liste." />
              </Carte>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
