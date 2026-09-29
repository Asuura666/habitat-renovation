import { type ReactElement, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams, useSearchParams } from "react-router";

import {
  cleBilanFournisseurs,
  cleLivraisons,
  type FiltresBilan,
  type LigneBilanChantier,
  type LigneLivraison,
  listerBilanChantiersFournisseur,
  listerBilanFournisseursGlobal,
  listerLivraisons,
  urlExportBilanChantiersFournisseur,
} from "../api/bilan";
import { type Anomalie, cleAnomalies, listerAnomalies } from "../api/anomalies";
import { CLE_COMPTE_A_REGLER, obtenirCompteARegler } from "../api/aTraiter";
import { CLE_FOURNISSEURS, listerFournisseurs } from "../api/referentiels";
import { type LivraisonAffichee, TableauLivraisons } from "../components/TableauLivraisons";
import { estMontantNul, formaterMontant, libelleMois, lireMois, mentionFactureAVerifier, moisApi } from "../lib/formats";
import { lienChantier } from "../lib/liens";
import {
  Chiffre,
  EnTetePage,
  EtatVide,
  FilAriane,
  libelleEcart,
  PastilleUrgence,
  phraseProbleme,
  sousTexteEcart,
  titreRegle,
  urgence,
} from "../ui";

const CLASSES_CHAMP_MOIS =
  "min-h-[44px] rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";

/** Une ligne de `GET /api/bilan/livraisons`, mise à la forme attendue par
 * `TableauLivraisons` (Task 13, spec §4.3) -- le chantier de chaque ligne
 * varie (`colonneChantier`), le fournisseur non (toujours celui de cette
 * fiche), même principe que le repli « Fournisseur à rattacher » des autres
 * écrans quand le référentiel ne l'a pas résolu. */
function versLivraisonAffichee(ligne: LigneLivraison): LivraisonAffichee {
  return {
    blocId: ligne.bloc_id,
    numeroBl: ligne.numero_bl,
    dateBl: ligne.date_bl,
    fournisseur: ligne.fournisseur ?? "Fournisseur à rattacher",
    chantier: ligne.chantier ?? "Chantier à rattacher",
    ligne,
  };
}

const CLASSES_BOUTON_LIEN =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

/** Cible d'au moins 44 px même sur un lien texte isolé. */
const CLASSES_LIEN_NOM =
  "inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

const CLASSES_CARTE = "rounded-carte border border-bordure bg-surface p-5";

/** Mois (`AAAA-MM`) et agence lus dans l'URL, posés par la liste. */
interface FiltresUrl {
  mois: string | undefined;
  agence: string | undefined;
}

/** Résumé de la période affichée (`surtitre` d'`EnTetePage`) — mise en
 * forme uniquement (aucun calcul métier). */
function texteSurtitre(filtres: FiltresUrl): string {
  const periode = filtres.mois !== undefined ? `Période : ${libelleMois(filtres.mois)}` : "Tous les mois";
  return filtres.agence ? `${periode} · Agence ${filtres.agence}` : periode;
}

function lienAvecFiltres(chemin: string, filtres: FiltresUrl): string {
  const parametres = new URLSearchParams();
  if (filtres.mois !== undefined) {
    parametres.set("mois", filtres.mois);
  }
  if (filtres.agence) {
    parametres.set("agence", filtres.agence);
  }
  const requete = parametres.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

/** Couleur d'un montant d'alerte ou d'écart : neutre quand il vaut zéro
 * (revue finale, constats ECRAN-15/TELEPHONE-11). */
function classeMontant(valeur: string, classeSiNonNul: string): string {
  return estMontantNul(valeur) ? "text-encre-2" : classeSiNonNul;
}

/** Destination d'une ligne « chantier concerné » : la fiche du chantier
 * quand il est identifié — au mois affiché ici (revue finale, constat
 * LIENS-13 : le mois se perdait en route) —, sinon l'écran « À régler »
 * filtré sur les chantiers à rattacher (`/a-regler?filtre=rattacher`,
 * voir `lib/liens.ts`). */
function destinationChantier(ligne: LigneBilanChantier, mois: string | undefined): string {
  return lienChantier(ligne.chantier_id, mois);
}

function nomChantierTexte(ligne: LigneBilanChantier): string {
  if (ligne.chantier_id === null) {
    return "Chantier à rattacher";
  }
  return ligne.nom_canonique ?? "Chantier à rattacher";
}

/** Carte téléphone (< `md`) « chantier concerné » — toute la carte est
 * cliquable ; fond `bg-surface` pour garder un contraste d'au moins 4,5:1
 * sur le montant d'écart. */
function CarteChantierConcerne({ ligne, mois }: { ligne: LigneBilanChantier; mois: string | undefined }): ReactElement {
  return (
    <li>
      <Link
        to={destinationChantier(ligne, mois)}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        <h3 className="mb-3 font-medium text-encre">{nomChantierTexte(ligne)}</h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-encre-2">Facturé</dt>
            <dd className="mt-0.5 font-mono font-medium text-encre">{formaterMontant(ligne.montants.facture_ht)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Écart</dt>
            <dd className={`mt-0.5 font-mono font-medium ${classeMontant(ligne.montants.en_ecart, "text-ecart-texte")}`}>
              {formaterMontant(ligne.montants.en_ecart)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Sans bon</dt>
            <dd className={`mt-0.5 font-mono font-medium ${classeMontant(ligne.montants.non_justifie, "text-alerte")}`}>
              {formaterMontant(ligne.montants.non_justifie)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Problèmes</dt>
            <dd className="mt-0.5 font-medium text-encre">{ligne.montants.nb_anomalies_ouvertes}</dd>
          </div>
        </dl>
      </Link>
    </li>
  );
}

function SectionChantiersConcernes({
  lignes,
  mois,
}: {
  lignes: LigneBilanChantier[];
  mois: string | undefined;
}): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun chantier concerné pour l'instant." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md, spec §7). */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <CarteChantierConcerne key={ligne.chantier_id ?? "non-resolu"} ligne={ligne} mois={mois} />
        ))}
      </ul>

      {/* Tableau — ordinateur (>= md). */}
      <div className="hidden overflow-x-auto rounded-carte border border-bordure md:block">
        <table className="w-full min-w-[640px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Chantiers concernés par ce fournisseur</caption>
          <thead className="bg-fond text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="px-5 py-3">
                Chantier
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Facturé
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Écart
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Sans bon
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Problèmes
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure bg-surface">
            {lignes.map((ligne) => (
              <tr key={ligne.chantier_id ?? "non-resolu"}>
                <th scope="row" className="px-5 py-3 text-left font-medium text-encre">
                  <Link to={destinationChantier(ligne, mois)} className={CLASSES_LIEN_NOM}>
                    {nomChantierTexte(ligne)}
                  </Link>
                </th>
                <td className="px-5 py-3 text-right font-mono text-encre">{formaterMontant(ligne.montants.facture_ht)}</td>
                <td className={`px-5 py-3 text-right font-mono ${classeMontant(ligne.montants.en_ecart, "text-ecart-texte")}`}>
                  {formaterMontant(ligne.montants.en_ecart)}
                </td>
                <td className={`px-5 py-3 text-right font-mono ${classeMontant(ligne.montants.non_justifie, "text-alerte")}`}>
                  {formaterMontant(ligne.montants.non_justifie)}
                </td>
                <td className="px-5 py-3 text-right text-encre">{ligne.montants.nb_anomalies_ouvertes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Une ligne « problème ouvert » (spec §5) : titre et phrase chiffrée via le
 * langage courant partagé (`ui/libelles.ts`), pastille d'urgence partagée
 * (`ui/PastilleUrgence.tsx`, revue finale, constat LIENS-12) ; ouvre le
 * détail du problème sur l'écran « À régler ». */
function CarteProbleme({ anomalie }: { anomalie: Anomalie }): ReactElement {
  return (
    <li>
      <Link
        to={`/a-regler/${anomalie.id}`}
        className="block rounded-carte border border-bordure bg-surface px-4 py-3 outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
          <span className="font-medium text-encre">{titreRegle(anomalie.regle)}</span>
          <PastilleUrgence urgence={urgence(anomalie.gravite)} />
        </div>
        <p className="text-sm text-encre">{phraseProbleme(anomalie)}</p>
      </Link>
    </li>
  );
}

function SectionProblemesOuverts({ anomalies }: { anomalies: Anomalie[] }): ReactElement {
  if (anomalies.length === 0) {
    return <EtatVide message="Aucun problème ouvert pour ce fournisseur." />;
  }
  return (
    <ul className="space-y-3">
      {anomalies.map((anomalie) => (
        <CarteProbleme key={anomalie.id} anomalie={anomalie} />
      ))}
    </ul>
  );
}

/**
 * Fiche fournisseur (spec §4, Task 9) : quatre `Chiffre` (Facturé,
 * Conforme, Écart prix ou quantité, Sans bon de livraison — mêmes montants
 * que les colonnes de `FournisseursListe`, tous fournis par le serveur ;
 * « Conforme » l'est depuis la revue finale, constat COUVERTURE-12, jamais
 * recalculé ici), chantiers concernés (lien `/chantiers/:id`), problèmes
 * ouverts (lien `/a-regler/:id`), factures du fournisseur, agences connues
 * et export. `mois`/`agence` sont lus dans l'URL (posés par la liste) et
 * reportés aux requêtes que l'API sait filtrer par mois de facture
 * (montants, chantiers), à leur export, au fil d'Ariane et aux liens vers
 * les chantiers — cette page ne montre pas elle-même de sélecteur.
 * « Problèmes ouverts » est la seule section qui n'en tient jamais compte :
 * `GET /api/anomalies` ne filtre que sur `created_at` (date de constat d'un
 * problème), qui n'a aucun rapport avec le mois de la facture — la section
 * le dit explicitement quand un filtre est actif ailleurs sur la page.
 *
 * Les montants viennent de la même requête que la liste
 * (`GET /api/bilan/fournisseurs`, filtrée) : la ligne correspondante y est
 * retrouvée par son identifiant, une simple recherche, jamais une somme ni
 * un recalcul. Le nom et les agences viennent de `GET /api/fournisseurs`
 * (référentiel), seule source qui connaît un fournisseur même sans aucune
 * facture.
 */
export function FicheFournisseur(): ReactElement {
  const { fournisseurId } = useParams();
  const [parametres, setParametres] = useSearchParams();
  const { hash } = useLocation();
  const filtresUrl: FiltresUrl = {
    mois: lireMois(parametres.get("mois")),
    agence: parametres.get("agence") || undefined,
  };
  const filtres: FiltresBilan = {
    mois: filtresUrl.mois !== undefined ? moisApi(filtresUrl.mois) : undefined,
    agence: filtresUrl.agence,
  };

  // Sélecteur de mois (Task 13, spec §4.2, correction 2) : même schéma que
  // `FournisseursListe.tsx::FormulaireFiltres` (`<input type="month">` +
  // `setSearchParams`/`{replace: true}`) -- les requêtes de cette fiche
  // lisent déjà `filtres.mois`, ce sélecteur ne fait qu'écrire dans l'URL.
  function changerMois(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur.trim() === "") {
      suivants.delete("mois");
    } else {
      suivants.set("mois", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  // Tuile « Conforme » cliquable (spec §4.3) : mène à la carte
  // « Livraisons » ci-dessous (ancre `#livraisons`), filtrée sur les bons
  // conformes (`?etat=conforme`) -- mois et agence affichés préservés.
  const parametresLivraisonsConformes = new URLSearchParams(parametres);
  parametresLivraisonsConformes.set("etat", "conforme");
  const lienLivraisonsConformes = `?${parametresLivraisonsConformes.toString()}#livraisons`;

  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });
  const bilanGlobal = useQuery({
    queryKey: cleBilanFournisseurs(null, filtres),
    queryFn: () => listerBilanFournisseursGlobal(filtres),
  });
  const chantiers = useQuery({
    queryKey: ["bilan", "chantiers-fournisseur", fournisseurId, filtres] as const,
    queryFn: () => listerBilanChantiersFournisseur(fournisseurId ?? "", filtres),
    enabled: fournisseurId !== undefined,
  });
  // `limite` au maximum de l'API (revue finale, constat COUVERTURE-22) :
  // jamais un plafond silencieux à 100 problèmes.
  const anomalies = useQuery({
    queryKey: cleAnomalies({ fournisseurId, limite: 500 }),
    queryFn: () => listerAnomalies({ fournisseurId, limite: 500 }),
    enabled: fournisseurId !== undefined,
  });
  // Carte « Livraisons » (Task 13, spec §4.3) : `GET /api/bilan/livraisons`
  // filtré sur ce fournisseur, tous chantiers confondus (`colonneChantier`,
  // voir `components/TableauLivraisons.tsx`) -- déjà trié par date de BL
  // décroissante par le serveur, jamais un second tri ici.
  const filtresLivraisons = { mois: filtres.mois, agence: filtres.agence, fournisseurId };
  const livraisonsQuery = useQuery({
    queryKey: cleLivraisons(filtresLivraisons),
    queryFn: () => listerLivraisons(filtresLivraisons),
    enabled: fournisseurId !== undefined,
  });
  const livraisons: LivraisonAffichee[] = (livraisonsQuery.data ?? []).map(versLivraisonAffichee);
  const periodeLivraisons = filtresUrl.mois !== undefined ? libelleMois(filtresUrl.mois) : null;
  const titreLivraisons = periodeLivraisons !== null ? `Livraisons — ${periodeLivraisons}` : "Livraisons";
  const messageAucuneLivraison =
    periodeLivraisons !== null
      ? `Aucune livraison en ${periodeLivraisons}.`
      : "Aucune livraison enregistrée pour ce fournisseur.";

  // Défilement jusqu'à la carte « Livraisons » une fois chargée (ancre
  // `#livraisons`, même mécanique que `#bloc-…` sur `FactureDetail.tsx`).
  useEffect(() => {
    if (livraisonsQuery.isSuccess && hash === "#livraisons") {
      window.document.getElementById("livraisons")?.scrollIntoView({ block: "start" });
    }
  }, [livraisonsQuery.isSuccess, hash]);

  // Même clé que `Gabarit`/`VueEnsemble`/`ARegler` (décision d'Ilane du
  // 24/09/2026, `docs/dette.md`) : seul endroit qui porte `controle_prix_
  // actif`, lu ici pour la tuile « Écart … » ci-dessous — `@tanstack/
  // react-query` partage le cache par clé, jamais un second appel réseau.
  const compteARegler = useQuery({ queryKey: CLE_COMPTE_A_REGLER, queryFn: obtenirCompteARegler });
  // Constat mineur 2 de la revue des contrôles de prix : le repli est
  // `false`, même valeur que le défaut serveur -- jamais un flash de
  // « Écart prix ou quantité » le temps que la requête réponde.
  const controlePrixActif = compteARegler.data?.controle_prix_actif ?? false;

  const fournisseur = fournisseurs.data?.find((f) => f.id === fournisseurId);
  const ligneMontants = bilanGlobal.data?.find((l) => l.fournisseur_id === fournisseurId);
  const nom = fournisseur?.nom ?? ligneMontants?.nom ?? "Fournisseur";

  const chargementEntete = fournisseurs.isPending || bilanGlobal.isPending;
  const erreurEntete = fournisseurs.isError || bilanGlobal.isError;

  return (
    <div className="space-y-6">
      <FilAriane
        elements={[
          { libelle: "Fournisseurs", vers: lienAvecFiltres("/fournisseurs", filtresUrl) },
          { libelle: nom },
        ]}
      />

      <EnTetePage
        surtitre={texteSurtitre(filtresUrl)}
        titre={nom}
        actions={
          <>
            <div className="flex items-center gap-2">
              <label htmlFor="filtre-mois" className="text-sm text-encre-2">
                Mois
              </label>
              <input
                id="filtre-mois"
                type="month"
                value={filtresUrl.mois ?? ""}
                onChange={(evenement) => changerMois(evenement.target.value)}
                className={CLASSES_CHAMP_MOIS}
              />
            </div>
            {/* Grille de prix du fournisseur (phase 3, tâche P5, spec §9) —
                lien près de l'en-tête, comme demandé par le plan. */}
            <Link to={`/fournisseurs/${fournisseurId ?? ""}/prix`} className={CLASSES_BOUTON_LIEN}>
              Grille de prix
            </Link>
            <a href={urlExportBilanChantiersFournisseur(fournisseurId ?? "", filtres)} className={CLASSES_BOUTON_LIEN}>
              Exporter pour Excel
            </a>
          </>
        }
      />

      {chargementEntete && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {erreurEntete && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger ce fournisseur.
        </p>
      )}

      {!chargementEntete && !erreurEntete && (
        <>
          {ligneMontants ? (
            <section aria-label="Chiffres du fournisseur" className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
              <Chiffre
                libelle="Facturé"
                valeur={formaterMontant(ligneMontants.montants.facture_ht)}
                sousTexte={mentionFactureAVerifier(ligneMontants.montants.facture_a_verifier)}
              />
              <Chiffre
                libelle="Conforme"
                valeur={formaterMontant(ligneMontants.montants.conforme)}
                ton={estMontantNul(ligneMontants.montants.conforme) ? "neutre" : "conforme"}
                vers={lienLivraisonsConformes}
              />
              <Chiffre
                libelle={libelleEcart(controlePrixActif)}
                valeur={formaterMontant(ligneMontants.montants.en_ecart)}
                sousTexte={sousTexteEcart(controlePrixActif)}
                ton={estMontantNul(ligneMontants.montants.en_ecart) ? "neutre" : "ecart"}
              />
              <Chiffre
                libelle="Sans bon de livraison"
                valeur={formaterMontant(ligneMontants.montants.non_justifie)}
                ton={estMontantNul(ligneMontants.montants.non_justifie) ? "neutre" : "alerte"}
              />
            </section>
          ) : (
            <EtatVide message="Aucune facture enregistrée pour ce fournisseur sur ces filtres." />
          )}

          <section aria-label="Livraisons" className={CLASSES_CARTE}>
            <h2 className="mb-4 font-titre text-xl font-medium text-encre">{titreLivraisons}</h2>
            {livraisonsQuery.isPending && (
              <p role="status" className="text-sm text-encre-2">
                Chargement…
              </p>
            )}
            {livraisonsQuery.isError && (
              <p role="alert" className="text-sm text-alerte">
                Impossible de charger les livraisons de ce fournisseur.
              </p>
            )}
            {livraisonsQuery.isSuccess && (
              <TableauLivraisons livraisons={livraisons} colonneChantier messageVide={messageAucuneLivraison} />
            )}
          </section>

          <section aria-label="Chantiers concernés" className={CLASSES_CARTE}>
            <h2 className="mb-4 font-titre text-xl font-medium text-encre">Chantiers concernés</h2>
            {chantiers.isPending && (
              <p role="status" className="text-sm text-encre-2">
                Chargement…
              </p>
            )}
            {chantiers.isError && (
              <p role="alert" className="text-sm text-alerte">
                Impossible de charger les chantiers de ce fournisseur.
              </p>
            )}
            {chantiers.data && <SectionChantiersConcernes lignes={chantiers.data} mois={filtresUrl.mois} />}
          </section>

          <section aria-label="Problèmes ouverts" className={CLASSES_CARTE}>
            <div className="mb-4">
              <h2 className="font-titre text-xl font-medium text-encre">
                Problèmes ouverts{anomalies.data ? ` · ${anomalies.data.length}` : ""}
              </h2>
              {(filtres.mois || filtres.agence) && (
                <p className="mt-1 text-sm text-encre-2">
                  Tous les problèmes encore ouverts chez ce fournisseur, quel que soit le mois ou
                  l'agence.
                </p>
              )}
            </div>
            {anomalies.isPending && (
              <p role="status" className="text-sm text-encre-2">
                Chargement…
              </p>
            )}
            {anomalies.isError && (
              <p role="alert" className="text-sm text-alerte">
                Impossible de charger les problèmes de ce fournisseur.
              </p>
            )}
            {anomalies.data && <SectionProblemesOuverts anomalies={anomalies.data} />}
            {/* Revue finale : l'historique des problèmes réglés de ce
                fournisseur (constat LIENS-14) et ses factures (constat
                COUVERTURE-13, spec §4 « fiche fournisseur : … factures ») —
                deux écrans existants, déjà filtrables, jamais dupliqués. */}
            <div className="mt-4 flex flex-wrap gap-x-6 border-t border-bordure pt-3 text-sm">
              <Link to={`/a-regler?fournisseur=${fournisseurId ?? ""}`} className={CLASSES_LIEN_NOM}>
                Régler les problèmes de ce fournisseur
              </Link>
              <Link to={`/a-regler?filtre=regles&fournisseur=${fournisseurId ?? ""}`} className={CLASSES_LIEN_NOM}>
                Voir l'historique
              </Link>
              <Link to={`/documents?filtre=factures&fournisseur=${fournisseurId ?? ""}`} className={CLASSES_LIEN_NOM}>
                Voir les factures de ce fournisseur
              </Link>
            </div>
          </section>

          <section aria-label="Agences connues" className={CLASSES_CARTE}>
            <h2 className="mb-4 font-titre text-xl font-medium text-encre">Agences connues</h2>
            {fournisseur === undefined || fournisseur.agences.length === 0 ? (
              <EtatVide message="Aucune agence connue pour ce fournisseur." />
            ) : (
              <ul className="space-y-3">
                {fournisseur.agences.map((agence) => (
                  <li key={agence.id} className="rounded-carte border border-bordure bg-fond p-4">
                    <p className="font-medium text-encre">{agence.nom}</p>
                    <p className="text-sm text-encre-2">{agence.adresse ?? "Adresse non renseignée"}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
