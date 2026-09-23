import { type FormEvent, type MouseEvent, type ReactElement, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import {
  cleBilanBl,
  cleBilanChantiers,
  cleBilanFournisseurs,
  type FiltresBilan,
  type LigneBilanBl,
  type LigneBilanFournisseur,
  listerBilanBl,
  listerBilanChantiers,
  listerBilanFournisseurs,
  urlExportBilanBl,
  urlExportBilanFournisseurs,
} from "../api/bilan";
import { cleAnomalies, type FiltresAnomalies, listerAnomalies } from "../api/anomalies";
import { ErreurApi } from "../api/client";
import {
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  type Chantier,
  ChantierEnDoubleErreur,
  listerChantiers,
  type ModificationChantier,
  modifierChantier,
} from "../api/referentiels";
import { cleTableauDeBord, obtenirTableauDeBord } from "../api/tableauDeBord";
import { formaterDate, formaterMontant, TIRET } from "../lib/formats";
import {
  Bouton,
  Carte,
  Chiffre,
  type Etat,
  EtatVide,
  FilAriane,
  PastilleEtat,
  phraseProbleme,
  titreRegle,
  urgence,
} from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";
const FILTRES_TOUS_MOIS: FiltresBilan = {};

const FORMATEUR_LIBELLE_MOIS = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  month: "long",
  year: "numeric",
});

/** « septembre 2026 » à partir d'un mois choisi au format `AAAA-MM-01`
 * (même représentation que `filtres.mois` sur `ChantiersListe`) — sert à
 * préciser la période des `Chiffre` de la fiche (fix round 1, constat 3) :
 * sans elle, « Facturé » n'indique jamais si le montant porte sur un mois
 * ou sur toute l'historique du chantier. */
function libelleMois(mois: string): string {
  return FORMATEUR_LIBELLE_MOIS.format(new Date(mois));
}

/** « Facturé — tous les mois » ou « Facturé en septembre 2026 » (fix round
 * 1, constat 3) : précise sur quelle période porte chaque `Chiffre`, sans
 * jamais recalculer le montant lui-même (toujours celui renvoyé par
 * l'API, filtré par le même `mois` que la requête qui l'a produit). */
function libelleAvecPeriode(base: string, mois: string | undefined): string {
  return mois !== undefined ? `${base} en ${libelleMois(mois)}` : `${base} — tous les mois`;
}

/** « septembre 2026 », ou `null` si aucun mois n'est choisi (fix round 2,
 * constat 1) : précise la période affichée par la carte « Livraisons »
 * (titre et état vide) — avant ce correctif, ni l'un ni l'autre
 * n'indiquait que la liste était filtrée par `?mois`, alors que les trois
 * `Chiffre` le disent déjà via `libelleAvecPeriode`. */
function libellePeriodeCourte(mois: string | undefined): string | null {
  return mois !== undefined ? libelleMois(mois) : null;
}

function libelleStatutBon(statut: string | null): string {
  if (statut === "recu") return "Reçu";
  if (statut === "non_recu") return "Jamais reçu";
  if (statut === "pas_de_bon") return "Livré sans bon";
  return "Statut inconnu";
}

const CLASSES_POINT_STATUT: Record<string, string> = {
  conforme: "bg-conforme",
  ecart: "bg-ecart",
  alerte: "bg-alerte",
  inconnu: "bg-encre-2",
};

/** Point de couleur + libellé (jamais la couleur seule, spec §2) résumant
 * l'état d'une ligne de livraison : reçu sans problème (vert), reçu avec un
 * problème ouvert (ambre, `nb_anomalies_ouvertes` déjà fourni par le
 * serveur — aucun calcul ici), jamais reçu/livré sans bon (rouge). */
function EtatBon({ ligne }: { ligne: LigneBilanBl }): ReactElement {
  let categorie: keyof typeof CLASSES_POINT_STATUT = "inconnu";
  if (ligne.statut_rapprochement === "recu") {
    categorie = ligne.montants.nb_anomalies_ouvertes > 0 ? "ecart" : "conforme";
  } else if (ligne.statut_rapprochement === "non_recu" || ligne.statut_rapprochement === "pas_de_bon") {
    categorie = "alerte";
  }
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${CLASSES_POINT_STATUT[categorie]}`} />
      {libelleStatutBon(ligne.statut_rapprochement)}
    </span>
  );
}

interface LivraisonAffichee {
  blocId: string;
  numeroBl: string | null;
  dateBl: string | null;
  fournisseur: string;
  ligne: LigneBilanBl;
}

function comparerDateDesc(a: LivraisonAffichee, b: LivraisonAffichee): number {
  if (a.dateBl === null && b.dateBl === null) return 0;
  if (a.dateBl === null) return 1;
  if (b.dateBl === null) return -1;
  return b.dateBl.localeCompare(a.dateBl);
}

function lienLivraison(ligne: LigneBilanBl): string {
  return ligne.bl_document_id !== null ? `/bl/${ligne.bl_document_id}` : `/documents/${ligne.facture_id}`;
}

function LigneLivraisonCarte({ livraison }: { livraison: LivraisonAffichee }): ReactElement {
  return (
    <li>
      <Link
        to={lienLivraison(livraison.ligne)}
        className="block rounded-lg border border-bordure bg-surface p-4 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="mb-2 flex items-start justify-between gap-3">
          <div>
            <p className="font-medium text-encre">BL {livraison.numeroBl ?? TIRET}</p>
            <p className="text-xs text-encre-2">{formaterDate(livraison.dateBl)} · {livraison.fournisseur}</p>
          </div>
          <p className="font-mono text-sm tabular-nums text-encre">
            {formaterMontant(livraison.ligne.montants.facture_ht)}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <EtatBon ligne={livraison.ligne} />
          <span className="text-encre-2">
            {livraison.ligne.montants.nb_anomalies_ouvertes} problème
            {livraison.ligne.montants.nb_anomalies_ouvertes > 1 ? "s" : ""}
          </span>
        </div>
      </Link>
    </li>
  );
}

/** Toute la ligne mène vers la page BL (brief : « chaque ligne vers
 * /bl/:bl_document_id […] sinon vers /documents/:facture_id »), comme dans
 * la maquette `FicheChantier` : navigation au clic sur la `<tr>` pour la
 * cible tactile la plus large possible, **et** un vrai lien accessible (N°
 * BL) pour le clavier et les lecteurs d'écran — jamais la `<tr>` seule, qui
 * ne serait pas atteignable sans souris. */
function LigneLivraisonTableau({ livraison, naviguer }: { livraison: LivraisonAffichee; naviguer: () => void }): ReactElement {
  // Garde contre la double navigation (fix round 2, constat 2) : le n° BL
  // porte un vrai <Link> (accessibilité clavier/lecteur d'écran) dont le
  // gestionnaire de clic (react-router `useLinkClickHandler`) fait
  // `preventDefault` puis navigue, mais ne fait jamais `stopPropagation` —
  // le clic remonte ensuite jusqu'à cette <tr>, qui naviguait une seconde
  // fois (deux entrées d'historique identiques, un premier « Retour » sans
  // effet visible) et, pour un Ctrl/Cmd+clic ouvrant le lien dans un
  // nouvel onglet, faisait quand même naviguer l'onglet courant. On
  // ignore donc les clics déjà traités par un lien (`defaultPrevented`
  // ou une cible à l'intérieur d'un `<a>`) et les clics avec modificateur
  // ou bouton autre que le clic gauche.
  function gererClicLigne(evenement: MouseEvent<HTMLTableRowElement>): void {
    if (evenement.defaultPrevented) return;
    if ((evenement.target as HTMLElement).closest("a") !== null) return;
    if (evenement.button !== 0 || evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) {
      return;
    }
    naviguer();
  }

  return (
    <tr
      onClick={gererClicLigne}
      className="cursor-pointer outline-none hover:bg-fond focus-within:bg-fond"
    >
      <td className="py-2.5 pl-2 text-encre">{formaterDate(livraison.dateBl)}</td>
      <td className="py-2.5 font-mono text-encre">
        <Link
          to={lienLivraison(livraison.ligne)}
          className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
        >
          {livraison.numeroBl ?? TIRET}
        </Link>
      </td>
      <td className="py-2.5 pr-2 text-encre">{livraison.fournisseur}</td>
      <td className="py-2.5 pr-2">
        <EtatBon ligne={livraison.ligne} />
      </td>
      <td className="py-2.5 pr-2 text-right font-mono tabular-nums text-encre">
        {formaterMontant(livraison.ligne.montants.facture_ht)}
      </td>
      <td className="py-2.5 pr-2 text-right text-encre">{livraison.ligne.montants.nb_anomalies_ouvertes}</td>
    </tr>
  );
}

function TableauLivraisons({ livraisons }: { livraisons: LivraisonAffichee[] }): ReactElement {
  const navigate = useNavigate();
  return (
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full text-sm">
        <caption className="sr-only">Livraisons du chantier</caption>
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
          <tr>
            <th scope="col" className="py-2 pl-2">Date</th>
            <th scope="col" className="py-2">N° BL</th>
            <th scope="col" className="py-2 pr-2">Fournisseur</th>
            <th scope="col" className="py-2 pr-2">Bon de livraison</th>
            <th scope="col" className="py-2 pr-2 text-right">Montant</th>
            <th scope="col" className="py-2 pr-2 text-right">Problèmes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-bordure">
          {livraisons.map((livraison) => (
            <LigneLivraisonTableau
              key={livraison.blocId}
              livraison={livraison}
              naviguer={() => navigate(lienLivraison(livraison.ligne))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Formulaire d'édition (nom, client, agence, actif — `PUT /api/chantiers
 * /{id}`, Task 1 de la refonte du front). */
function FormulaireEdition({
  chantier,
  onFermer,
}: {
  chantier: Chantier;
  onFermer: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [nomCanonique, setNomCanonique] = useState(chantier.nom_canonique);
  const [client, setClient] = useState(chantier.client ?? "");
  const [agence, setAgence] = useState(chantier.agence ?? "");
  const [actif, setActif] = useState(chantier.actif);

  const edition = useMutation({
    mutationFn: (modification: ModificationChantier) => modifierChantier(chantier.id, modification),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS }),
        queryClient.invalidateQueries({ queryKey: cleBilanChantiers(FILTRES_TOUS_MOIS) }),
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX }),
      ]);
      onFermer();
    },
  });

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof ChantierEnDoubleErreur) {
      return "Un autre chantier porte déjà ce nom.";
    }
    if (erreur instanceof ErreurApi) {
      return erreur.detail;
    }
    return "Une erreur est survenue, réessayez.";
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    edition.mutate({
      nomCanonique,
      client: client.trim() === "" ? null : client.trim(),
      agence: agence.trim() === "" ? null : agence.trim(),
      actif,
    });
  }

  return (
    <Carte titre="Modifier le chantier">
      <form onSubmit={soumettre} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="edition-nom" className={CLASSES_LABEL}>
            Nom du chantier
          </label>
          <input
            id="edition-nom"
            type="text"
            value={nomCanonique}
            onChange={(evenement) => setNomCanonique(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="edition-client" className={CLASSES_LABEL}>
            Client
          </label>
          <input
            id="edition-client"
            type="text"
            value={client}
            onChange={(evenement) => setClient(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="edition-agence" className={CLASSES_LABEL}>
            Agence
          </label>
          <input
            id="edition-agence"
            type="text"
            value={agence}
            onChange={(evenement) => setAgence(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div className="flex items-end">
          <label htmlFor="edition-actif" className="flex min-h-[44px] items-center gap-2 text-sm text-encre">
            <input
              id="edition-actif"
              type="checkbox"
              checked={actif}
              onChange={(evenement) => setActif(evenement.target.checked)}
              className="h-4 w-4 rounded border-bordure text-accent focus-visible:ring-2 focus-visible:ring-accent"
            />
            Chantier actif
          </label>
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <Bouton type="submit" disabled={nomCanonique.trim() === "" || edition.isPending}>
            Enregistrer
          </Bouton>
          <Bouton type="button" variante="secondaire" onClick={onFermer}>
            Annuler
          </Bouton>
        </div>
        {edition.isError && (
          <p role="alert" className="text-sm text-alerte sm:col-span-2">
            {messageErreur(edition.error)}
          </p>
        )}
      </form>
    </Carte>
  );
}

export function FicheChantier(): ReactElement {
  const { chantierId } = useParams();
  const [parametres] = useSearchParams();
  const [editionOuverte, setEditionOuverte] = useState(false);
  const id = chantierId ?? "";

  // Mois choisi (fix round 1, constat 3) : lu depuis `?mois=` (même
  // représentation `AAAA-MM-01` que `ChantiersListe`, transmise aussi bien
  // par ses liens que par l'ancienne redirection `/bilan/:c?mois=…`).
  // Absent de l'URL -> pas de mois : les montants portent alors sur tout
  // l'historique du chantier (`FILTRES_TOUS_MOIS`), comme avant le choix
  // d'une période, et aucun état calculé (`PastilleEtat`) n'est affiché —
  // `/api/tableau-de-bord` n'a de sens que pour un mois précis.
  const moisParam = parametres.get("mois") ?? undefined;
  const moisChoisi = moisParam !== undefined;
  const filtresActifs: FiltresBilan = moisChoisi ? { mois: moisParam } : FILTRES_TOUS_MOIS;

  // Titre et état vide de la carte « Livraisons » (fix round 2, constat 1) :
  // précisent désormais la période affichée, comme les trois `Chiffre`.
  const periodeLivraisons = libellePeriodeCourte(moisParam);
  const titreLivraisons = periodeLivraisons !== null ? `Livraisons — ${periodeLivraisons}` : "Livraisons";
  const messageAucuneLivraison =
    periodeLivraisons !== null
      ? `Aucune livraison en ${periodeLivraisons}.`
      : "Aucune livraison enregistrée pour ce chantier.";

  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });
  const bilanChantiers = useQuery({
    queryKey: cleBilanChantiers(filtresActifs),
    queryFn: () => listerBilanChantiers(filtresActifs),
  });
  const tableauDeBord = useQuery({
    queryKey: cleTableauDeBord(moisParam ?? ""),
    queryFn: () => obtenirTableauDeBord(moisParam ?? ""),
    enabled: moisChoisi,
  });
  const fournisseurs = useQuery({
    queryKey: cleBilanFournisseurs(id, filtresActifs),
    queryFn: () => listerBilanFournisseurs(id, filtresActifs),
    enabled: chantierId !== undefined,
  });
  const filtresAnomalies: FiltresAnomalies = { chantierId: id };
  const anomalies = useQuery({
    queryKey: cleAnomalies(filtresAnomalies),
    queryFn: () => listerAnomalies(filtresAnomalies),
    enabled: chantierId !== undefined,
  });

  const fournisseursResolus: LigneBilanFournisseur[] =
    fournisseurs.data?.filter((f): f is LigneBilanFournisseur & { fournisseur_id: string } => f.fournisseur_id !== null) ?? [];

  const blParFournisseur = useQueries({
    queries: fournisseursResolus.map((fournisseur) => ({
      queryKey: cleBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs),
      queryFn: () => listerBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs),
      enabled: chantierId !== undefined,
    })),
  });

  // Fournisseurs/BL *sans* filtre de mois (fix round 2, constat 1), pour
  // « Dernière livraison reçue » ci-dessous uniquement — jamais pour la
  // carte « Livraisons » elle-même, qui reste filtrée par `filtresActifs`.
  // Mêmes clés que `fournisseurs`/`blParFournisseur` quand aucun mois
  // n'est choisi (`filtresActifs === FILTRES_TOUS_MOIS`) : `@tanstack/
  // react-query` partage alors le cache par clé, donc pas de requête
  // réseau en double dans ce cas.
  const fournisseursTous = useQuery({
    queryKey: cleBilanFournisseurs(id, FILTRES_TOUS_MOIS),
    queryFn: () => listerBilanFournisseurs(id, FILTRES_TOUS_MOIS),
    enabled: chantierId !== undefined,
  });
  const fournisseursTousResolus: LigneBilanFournisseur[] =
    fournisseursTous.data?.filter(
      (f): f is LigneBilanFournisseur & { fournisseur_id: string } => f.fournisseur_id !== null,
    ) ?? [];
  const blTousParFournisseur = useQueries({
    queries: fournisseursTousResolus.map((fournisseur) => ({
      queryKey: cleBilanBl(id, fournisseur.fournisseur_id as string, FILTRES_TOUS_MOIS),
      queryFn: () => listerBilanBl(id, fournisseur.fournisseur_id as string, FILTRES_TOUS_MOIS),
      enabled: chantierId !== undefined,
    })),
  });

  const chantier = chantiers.data?.find((c) => c.id === id);
  const ligneBilan = bilanChantiers.data?.find((l) => l.chantier_id === id);
  // Pastille d'état (fix round 1, constat 3) : uniquement quand un mois est
  // choisi — avant, elle portait toujours sur le mois courant implicite,
  // affiché sans le dire à côté de chiffres qui pouvaient porter sur toute
  // la durée du chantier (deux périodes différentes sur le même écran).
  const etatChoisi = moisChoisi
    ? (tableauDeBord.data?.chantiers.find((c) => c.chantier_id === id)?.etat as Etat | undefined)
    : undefined;

  const livraisonsChargees = fournisseurs.isSuccess && blParFournisseur.every((requete) => requete.isSuccess);
  const livraisons: LivraisonAffichee[] = livraisonsChargees
    ? blParFournisseur
        .flatMap((requete, index) =>
          (requete.data ?? []).map((ligne) => ({
            blocId: ligne.bloc_id,
            numeroBl: ligne.numero_bl,
            dateBl: ligne.date_bl,
            fournisseur: fournisseursResolus[index]?.nom ?? "Fournisseur non résolu",
            ligne,
          })),
        )
        .sort(comparerDateDesc)
    : [];
  // « Dernière livraison reçue » (fix round 1, constat 2 ; recalculée sans
  // filtre de mois au fix round 2, constat 1) : seules les lignes où une
  // photo de BL a réellement été rattachée (`bl_document_id !== null`)
  // comptent comme une livraison reçue — les lignes « Jamais reçu »/« Livré
  // sans bon » n'en sont pas une. `date_bl` reste la date imprimée sur le
  // bon, pas une date de dépôt (celle-ci n'est pas exposée par ligne côté
  // serveur, voir docs/dette.md) : le libellé affiché ci-dessous le dit
  // explicitement, jamais « déposé ». Calculée sur `blTousParFournisseur`
  // (sans `?mois`, voir ci-dessus) : avant ce correctif, elle portait sur
  // `livraisons`, déjà filtrée par le mois choisi — un chantier livré en
  // août et en septembre, filtré sur octobre, affichait « Aucune livraison
  // reçue », une affirmation fausse.
  const livraisonsToutesChargees =
    fournisseursTous.isSuccess && blTousParFournisseur.every((requete) => requete.isSuccess);
  const livraisonsRecues: LivraisonAffichee[] = livraisonsToutesChargees
    ? blTousParFournisseur
        .flatMap((requete, index) =>
          (requete.data ?? []).map((ligne) => ({
            blocId: ligne.bloc_id,
            numeroBl: ligne.numero_bl,
            dateBl: ligne.date_bl,
            fournisseur: fournisseursTousResolus[index]?.nom ?? "Fournisseur non résolu",
            ligne,
          })),
        )
        .filter((livraison) => livraison.ligne.bl_document_id !== null)
        .sort(comparerDateDesc)
    : [];
  const derniereLivraisonRecue = livraisonsRecues[0]?.dateBl ?? null;

  if (chantiers.isPending) {
    return <p role="status" className="text-sm text-encre-2">Chargement…</p>;
  }
  if (chantiers.isError) {
    return <p role="alert" className="text-sm text-alerte">Impossible de charger ce chantier.</p>;
  }
  if (chantier === undefined) {
    return (
      <div className="space-y-4">
        <FilAriane elements={[{ libelle: "Chantiers", vers: "/chantiers" }, { libelle: "Chantier introuvable" }]} />
        <EtatVide message="Ce chantier est introuvable." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <FilAriane elements={[{ libelle: "Chantiers", vers: "/chantiers" }, { libelle: chantier.nom_canonique }]} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h1 className="font-titre text-3xl font-medium text-encre">{chantier.nom_canonique}</h1>
          <div className="flex flex-wrap gap-4 text-sm text-encre">
            <span>Client : <strong className="font-medium">{chantier.client ?? "Non renseigné"}</strong></span>
            <span>Agence : {chantier.agence ?? "Non renseignée"}</span>
            <span>
              Dernière livraison reçue :{" "}
              {!livraisonsToutesChargees
                ? "Chargement…"
                : derniereLivraisonRecue === null
                  ? "Aucune livraison reçue"
                  : formaterDate(derniereLivraisonRecue)}
            </span>
            {!chantier.actif && <span className="font-medium text-alerte">Chantier inactif</span>}
            {moisChoisi && (
              <Link
                to={`/chantiers/${id}`}
                className="font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              >
                Voir tous les mois
              </Link>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {etatChoisi !== undefined && <PastilleEtat etat={etatChoisi} />}
          <Bouton variante="secondaire" onClick={() => setEditionOuverte((ouvert) => !ouvert)}>
            Modifier
          </Bouton>
        </div>
      </header>

      {editionOuverte && <FormulaireEdition chantier={chantier} onFermer={() => setEditionOuverte(false)} />}

      <section aria-label="Chiffres du chantier" className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Chiffre
          libelle={libelleAvecPeriode("Facturé", moisParam)}
          valeur={formaterMontant(ligneBilan?.montants.facture_ht ?? null)}
        />
        <Chiffre
          libelle={libelleAvecPeriode("Écart prix ou quantité", moisParam)}
          valeur={formaterMontant(ligneBilan?.montants.en_ecart ?? null)}
          ton="ecart"
        />
        <Chiffre
          libelle={libelleAvecPeriode("Sans bon de livraison", moisParam)}
          valeur={formaterMontant(ligneBilan?.montants.non_justifie ?? null)}
          ton="alerte"
        />
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Carte titre={titreLivraisons} className="flex flex-col lg:col-span-2">
          {fournisseurs.isPending && <p role="status" className="text-sm text-encre-2">Chargement…</p>}
          {fournisseurs.isError && <p role="alert" className="text-sm text-alerte">Impossible de charger les fournisseurs du chantier.</p>}
          {fournisseurs.isSuccess && !livraisonsChargees && (
            <p role="status" className="text-sm text-encre-2">Chargement…</p>
          )}
          {livraisonsChargees && livraisons.length === 0 && <EtatVide message={messageAucuneLivraison} />}
          {livraisonsChargees && livraisons.length > 0 && (
            <>
              <ul className="space-y-3 md:hidden">
                {livraisons.map((livraison) => (
                  <LigneLivraisonCarte key={livraison.blocId} livraison={livraison} />
                ))}
              </ul>
              <TableauLivraisons livraisons={livraisons} />
            </>
          )}

          {/* Pied de carte (fix round 2, constat 3) : la maquette FicheChantier
              place ces liens en pied de carte (margin-top:auto), pas dans
              l'en-tête — l'en-tête ne tient que le titre. Les exports par
              fournisseur (fix round 1, constat 4) sont regroupés sous un seul
              libellé « Exporter pour Excel » plutôt que d'ajouter un lien de
              plus par fournisseur à côté du titre : avant ce correctif, ces
              liens s'empilaient sur 4 lignes ou plus à 375 px et réduisaient
              chaque cible à environ 20 px de haut, sous les 44 px exigés. */}
          <div className="mt-4 flex flex-col gap-3 border-t border-bordure pt-4 text-sm md:mt-auto md:flex-row md:items-start md:justify-between md:gap-6">
            <Link
              to={`/documents?chantier=${id}`}
              className="inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              Voir les documents du chantier
            </Link>
            <div className="flex flex-col gap-1 md:items-end">
              <span className="text-xs font-medium uppercase tracking-wide text-encre-2">Exporter pour Excel</span>
              <a
                href={urlExportBilanFournisseurs(id, filtresActifs)}
                className="inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              >
                Récapitulatif par fournisseur (CSV)
              </a>
              {fournisseursResolus.map((fournisseur) => (
                <a
                  key={fournisseur.fournisseur_id}
                  href={urlExportBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs)}
                  className="inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Exporter les livraisons {fournisseur.nom} (CSV)
                </a>
              ))}
            </div>
          </div>
        </Carte>

        <Carte titre={`Problèmes ouverts · ${anomalies.data?.length ?? 0}`}>
          {anomalies.isPending && <p role="status" className="text-sm text-encre-2">Chargement…</p>}
          {anomalies.isError && <p role="alert" className="text-sm text-alerte">Impossible de charger les problèmes.</p>}
          {anomalies.data && anomalies.data.length === 0 && (
            <EtatVide message="Aucun problème ouvert sur ce chantier." />
          )}
          {anomalies.data && anomalies.data.length > 0 && (
            <ul className="space-y-2">
              {anomalies.data.map((anomalie) => (
                <li key={anomalie.id}>
                  <Link
                    to={`/a-regler/${anomalie.id}`}
                    className="block rounded-lg border border-bordure bg-fond p-3 outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <p className="flex items-center justify-between gap-2 text-sm font-semibold text-encre">
                      {titreRegle(anomalie.regle)}
                      <span className="text-xs font-medium text-encre-2">{urgence(anomalie.gravite)}</span>
                    </p>
                    <p className="mt-1 text-sm text-encre-2">{phraseProbleme(anomalie)}</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Carte>
      </div>
    </div>
  );
}
