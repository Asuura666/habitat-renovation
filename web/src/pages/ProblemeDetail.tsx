import { type FormEvent, type ReactElement, type ReactNode, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  type AliasEnAttente,
  type ArticleAValider,
  type ChantierACompleter,
  type DocumentATraiter,
} from "../api/aTraiter";
import { type Anomalie, traiterAnomalie } from "../api/anomalies";
import { ErreurApi } from "../api/client";
import { choisirChantierDocument } from "../api/documents";
import { invaliderApresChangementAnomalies } from "../api/invalidations";
import {
  type Chantier,
  ChantierEnDoubleErreur,
  CLE_CHANTIERS,
  creerChantier,
  validerArticle,
} from "../api/referentiels";
import { AliasCarte } from "../components/AliasCarte";
import { AvisIA } from "../components/AvisIA";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { CHANTIER_A_RATTACHER, lienBon, lienFacture } from "../lib/liens";
import { libelleMotif } from "../lib/motifs";
import {
  Bouton,
  Carte,
  dateHeureOuTiret,
  dateOuTiret,
  montantOuTiret,
  phraseProbleme,
  pointsOuAucun,
  pointsOuTiret,
  quantiteOuTiret,
  texteOuTiret,
  titreRegle,
  type TonChiffre,
  urgence,
} from "../ui";
import { categorieFiltreProbleme, type Probleme, titreDocument, type Urgence } from "./ARegler";

/**
 * Panneau de détail de l'écran « À régler » (Task 6) : monté à droite par
 * `ARegler.tsx` en `lg+`, et comme page plein écran (même composant) en
 * dessous — voir `App.tsx`, route `a-regler/:id`. Un seul composant par
 * type de problème (`probleme.kind`) : traitement d'une anomalie
 * (commentaire obligatoire + « Contesté »/« Ignorer »), lien de correction
 * d'un document « à vérifier », rattachement d'un alias (réutilise
 * `AliasCarte`), validation d'un article.
 */

const LIBELLES_CATEGORIE: Record<string, string> = {
  bl: "BL manquant",
  prix: "Prix",
  quantites: "Quantités",
  rattacher: "À rattacher",
  illisible: "Bon illisible",
  autre: "Autre",
};

const CLASSES_KICKER: Record<Urgence, string> = {
  Urgent: "text-alerte",
  "À voir": "text-ecart-texte",
  Info: "text-encre-2",
};

// `ecart` en #7a4a00 (texte d'écart foncé de la charte) plutôt que
// `text-ecart-texte` (#a86400) : sur le fond ivoire de l'encart « Pourquoi
// c'est signalé », ce dernier n'atteignait que 4,26:1, sous le 4,5:1 exigé
// (revue finale, constat COUVERTURE-24).
const CLASSES_TON: Record<TonChiffre, string> = {
  neutre: "text-encre",
  conforme: "text-conforme",
  ecart: "text-[#7a4a00]",
  alerte: "text-alerte",
};

// Liens texte isolés du panneau : cible d'au moins 44 px de haut, au
// téléphone comme à l'ordinateur (revue finale, constats TELEPHONE-7 et
// COUVERTURE-24).
const CLASSES_LIEN =
  "inline-flex min-h-[44px] items-center font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent";

interface ChiffreProbleme {
  libelle: string;
  valeur: string;
  ton?: TonChiffre;
}

/** 2 à 3 valeurs chiffrées nommées justifiant l'anomalie (brief Task 6),
 * tirées de `detail` sans aucun calcul (mêmes clés que `phraseProbleme`),
 * avec les gardes partagées de `ui/libelles.ts` (revue finale, constat
 * LIENS-12 : elles étaient recopiées dans `ARegler.tsx`). Une règle inconnue
 * n'affiche aucun chiffre (revue finale, constat COUVERTURE-19 : les clés
 * brutes de `detail`, « pu_facture : 12.5 », étaient du jargon). */
function chiffresProbleme(anomalie: Anomalie): ChiffreProbleme[] {
  const { detail, regle, gravite } = anomalie;
  const tonPrincipal: TonChiffre | undefined =
    gravite === "haute" ? "alerte" : gravite === "moyenne" ? "ecart" : undefined;

  switch (regle) {
    case "R01":
    case "R02":
      return [
        { libelle: "Montant du bon", valeur: montantOuTiret(detail, "montant_ht"), ton: tonPrincipal },
        // Fix round 1, finding 1 : `date_bl` vaut le tiret cadratin quand
        // le bon n'a pas de date lue (`app/modules/rules/rules/R01.py`,
        // `R02.py`) — jamais passé brut à `formaterDate` (garde
        // `dateOuTiret`, voir `ARegler.tsx`).
        { libelle: "Daté du", valeur: dateOuTiret(detail, "date_bl") },
      ];
    case "R03":
    case "R04":
      return [
        { libelle: "Facturé", valeur: quantiteOuTiret(detail, "qte_facture") },
        { libelle: "Sur le bon", valeur: quantiteOuTiret(detail, "qte_bl") },
        { libelle: "Écart", valeur: quantiteOuTiret(detail, "ecart"), ton: tonPrincipal },
      ];
    case "R05":
      return [
        { libelle: "Quantité", valeur: quantiteOuTiret(detail, "qte") },
        { libelle: "Montant", valeur: montantOuTiret(detail, "montant"), ton: tonPrincipal },
      ];
    case "R06":
      return [
        { libelle: "Quantité livrée", valeur: quantiteOuTiret(detail, "qte") },
        { libelle: "Jours écoulés", valeur: texteOuTiret(detail, "jours") },
      ];
    case "R07":
    case "R08":
      return [
        { libelle: "Facturé", valeur: montantOuTiret(detail, "pu_facture"), ton: tonPrincipal },
        { libelle: "Prix habituel", valeur: montantOuTiret(detail, "mediane") },
        { libelle: "Écart", valeur: `+${pointsOuTiret(detail, "ecart_pct")}`, ton: tonPrincipal },
      ];
    case "R09":
      return [
        { libelle: "Remise habituelle", valeur: pointsOuTiret(detail, "remise_habituelle") },
        { libelle: "Remise appliquée", valeur: pointsOuAucun(detail, "remise_appliquee"), ton: tonPrincipal },
      ];
    case "R10":
    case "R11":
      return [
        { libelle: "Somme des lignes", valeur: montantOuTiret(detail, "somme") },
        { libelle: "Total du document", valeur: montantOuTiret(detail, "total") },
        { libelle: "Écart", valeur: montantOuTiret(detail, "ecart"), ton: tonPrincipal },
      ];
    case "R12":
      return [
        { libelle: "Montant du bon", valeur: montantOuTiret(detail, "montant_ht"), ton: tonPrincipal },
        { libelle: "Déjà facturé sur", valeur: texteOuTiret(detail, "autre_facture") },
      ];
    case "R13":
      return [{ libelle: "Montant", valeur: montantOuTiret(detail, "montant"), ton: tonPrincipal }];
    case "R14":
      return [{ libelle: "En attente depuis", valeur: `${texteOuTiret(detail, "heures")} heures` }];
    case "R15":
      return [
        // Fix round 1, finding 1 : même garde que R01/R02 ci-dessus,
        // appliquée à `depose_le` (`app/modules/rules/rules/R15.py`).
        { libelle: "Déposé le", valeur: dateHeureOuTiret(detail, "depose_le") },
        { libelle: "En attente depuis", valeur: `${texteOuTiret(detail, "heures")} heures` },
      ];
    case "R16":
      return [
        // Fix round 1, finding 1 : même garde, appliquée à
        // `dernier_depot` (`app/modules/rules/rules/R16.py`).
        { libelle: "Dernier dépôt", valeur: dateHeureOuTiret(detail, "dernier_depot") },
        { libelle: "BL facturés depuis", valeur: texteOuTiret(detail, "bl_factures_depuis") },
      ];
    case "R17":
      return [
        { libelle: "Quantité", valeur: quantiteOuTiret(detail, "qte") },
        { libelle: "Conditionnement", valeur: texteOuTiret(detail, "conditionnement") },
      ];
    case "R18":
      return [
        { libelle: "Nom lu sur le bon", valeur: texteOuTiret(detail, "nom_lu") },
        { libelle: "Nom indiqué par l'employé", valeur: texteOuTiret(detail, "legende") },
      ];
    // Phase 3, tâche P9 (spec §5.2) : les mêmes clés que `phraseProbleme`
    // (`ui/libelles.ts`), en chiffres nommés plutôt qu'en phrase.
    case "R19":
    case "R21":
      return [
        { libelle: "Prix du bon", valeur: montantOuTiret(detail, "prix_bon"), ton: tonPrincipal },
        { libelle: "Prix de la grille", valeur: montantOuTiret(detail, "prix_grille") },
        { libelle: "Écart", valeur: pointsOuTiret(detail, "ecart_pct"), ton: tonPrincipal },
      ];
    case "R20":
      return [
        { libelle: "Prix du bon", valeur: montantOuTiret(detail, "prix_bon"), ton: tonPrincipal },
        { libelle: "Dernier prix facturé", valeur: montantOuTiret(detail, "dernier_prix") },
        { libelle: "Écart", valeur: pointsOuTiret(detail, "ecart_pct"), ton: tonPrincipal },
      ];
    case "R22":
      return [{ libelle: "Prix du bon", valeur: montantOuTiret(detail, "prix_bon"), ton: tonPrincipal }];
    case "R23":
      return [
        { libelle: "Prix du bon", valeur: montantOuTiret(detail, "prix_bon") },
        { libelle: "Ressemblance", valeur: pointsOuTiret(detail, "ressemblance") },
      ];
    case "R24": {
      // Fix relecture spec, tour 1, constat 1 : `unite_grille` n'est
      // renseigné que lorsque c'est la grille qui est non comparable
      // (`R24.py`) -- quand c'est la dernière facture, on bascule sur
      // `unite_dernier_prix`, même choix que `phraseProbleme` ci-dessus
      // (`ui/libelles.ts`, case "R24").
      const uniteGrille = texteOuTiret(detail, "unite_grille");
      const [libelleReference, valeurReference] =
        uniteGrille !== TIRET
          ? ["Unité de la grille", uniteGrille]
          : ["Unité de la dernière facture", texteOuTiret(detail, "unite_dernier_prix")];
      return [
        { libelle: "Unité du bon", valeur: texteOuTiret(detail, "unite_bon"), ton: tonPrincipal },
        { libelle: libelleReference, valeur: valeurReference },
      ];
    }
    case "R25":
      return [
        { libelle: "Date de la grille", valeur: dateOuTiret(detail, "date_grille") },
        { libelle: "Âge de la grille", valeur: `${texteOuTiret(detail, "age_mois")} mois` },
      ];
    default:
      return [];
  }
}

function messageErreurTraitement(erreur: unknown): string {
  if (erreur instanceof ErreurApi && erreur.status === 409) {
    return "Ce problème a déjà été traité entre-temps : rechargez la liste.";
  }
  if (erreur instanceof ErreurApi && erreur.status === 422) {
    return "Le commentaire est obligatoire (1 à 500 caractères).";
  }
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return "Une erreur est survenue, réessayez.";
}

/** Recréé le style « bouton principal » d'`ui/Bouton.tsx` pour une vraie
 * navigation (`<Link>`, accessibilité — jamais un bouton avec un gestionnaire
 * de clic pour changer de page) : `Bouton` ne rend qu'un `<button>`, et ce
 * fichier n'a pas le droit de le modifier (règle globale de la refonte). */
function LienPrincipal({ to, children }: { to: string; children: ReactNode }): ReactElement {
  return (
    <Link
      to={to}
      className="mt-auto inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-accent bg-accent px-4 py-2 text-center text-sm font-medium text-white outline-none transition-colors hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
    >
      {children}
    </Link>
  );
}

function Kicker({ probleme }: { probleme: Probleme }): ReactElement {
  const urgenceProbleme = probleme.kind === "anomalie" ? urgence(probleme.anomalie.gravite) : "À voir";
  const categorie = LIBELLES_CATEGORIE[categorieFiltreProbleme(probleme)] ?? "Problème";
  return (
    <p className={`text-xs font-semibold uppercase tracking-wide ${CLASSES_KICKER[urgenceProbleme]}`}>
      {urgenceProbleme} · {categorie}
    </p>
  );
}

function FormulaireTraitement({
  anomalie,
  onTraitementReussi,
}: {
  anomalie: Anomalie;
  onTraitementReussi: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [commentaire, setCommentaire] = useState("");

  const traitement = useMutation({
    mutationFn: (statut: "traitee" | "ignoree") => traiterAnomalie(anomalie.id, { statut, commentaire: commentaire.trim() }),
    onSuccess: async () => {
      // Invalidation après succès (brief Task 6) : anomalies (pastille du
      // gabarit incluse), tableau de bord, bilan, comparaison des bons —
      // même aide que toute autre écriture qui change des problèmes (revue
      // finale, constat LIENS-4).
      await invaliderApresChangementAnomalies(queryClient);
      setCommentaire("");
      onTraitementReussi();
    },
  });

  if (anomalie.statut !== "ouverte") {
    return (
      <p className="text-sm text-encre-2">
        {anomalie.statut === "traitee" ? "Contesté auprès du fournisseur" : "Ignoré, jugé normal"}
        {anomalie.traitee_par !== null ? ` par ${anomalie.traitee_par}` : ""}
        {anomalie.traitee_le !== null ? ` le ${formaterDateHeure(anomalie.traitee_le)}` : ""}
        {anomalie.commentaire !== null && anomalie.commentaire !== "" ? ` — ${anomalie.commentaire}` : ""}
      </p>
    );
  }

  const soumissionValide = commentaire.trim() !== "";

  function soumettre(evenement: FormEvent<HTMLFormElement>, statut: "traitee" | "ignoree"): void {
    evenement.preventDefault();
    traitement.mutate(statut);
  }

  return (
    <div className="mt-auto flex flex-col gap-3">
      <div>
        <label htmlFor={`commentaire-${anomalie.id}`} className="mb-1 block text-sm font-semibold text-encre">
          Commentaire (obligatoire)
        </label>
        <textarea
          id={`commentaire-${anomalie.id}`}
          value={commentaire}
          onChange={(evenement) => setCommentaire(evenement.target.value)}
          rows={3}
          maxLength={500}
          className="w-full resize-none rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <form onSubmit={(evenement) => soumettre(evenement, "traitee")} className="flex-1">
          <Bouton type="submit" disabled={!soumissionValide || traitement.isPending} className="w-full">
            Contesté auprès du fournisseur
          </Bouton>
        </form>
        <form onSubmit={(evenement) => soumettre(evenement, "ignoree")} className="flex-1">
          <Bouton
            type="submit"
            variante="secondaire"
            disabled={!soumissionValide || traitement.isPending}
            className="w-full"
          >
            C'est normal, ignorer
          </Bouton>
        </form>
      </div>
      {traitement.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreurTraitement(traitement.error)}
        </p>
      )}
    </div>
  );
}

interface CandidatR18 {
  id: string;
  nom: string;
}

/** Candidats d'une alerte R18, dans l'ordre de la décision de chantier
 * (`detail.candidats` séparés par « / », `detail.candidats_ids` par « , »
 * -- `rules/rules/R18.py`) : un bouton « C'est <nom> » par candidat. Un
 * candidat sans id correspondant (jamais censé arriver, `nom_pour_creation`
 * garantit toujours autant de noms que d'ids) est ignoré, défensif. */
function candidatsR18(anomalie: Anomalie): CandidatR18[] {
  const { detail } = anomalie;
  const noms = detail.candidats !== undefined && detail.candidats !== "" ? detail.candidats.split(" / ") : [];
  const ids =
    detail.candidats_ids !== undefined && detail.candidats_ids !== "" ? detail.candidats_ids.split(",") : [];
  return noms.flatMap((nom, index) => {
    const id = ids[index];
    return id !== undefined && id !== "" ? [{ id, nom }] : [];
  });
}

/** Levée par la mutation d'« Autre chantier… » (fix round 1 de la revue de
 * cette tâche, même piège identifié par `AliasCarte::RattachementApres
 * CreationErreur`) quand `creerChantier` a réussi mais que
 * `choisirChantierDocument` échoue ensuite : le chantier existe déjà en
 * base, ce n'est pas une erreur de création -- un réessai doit réutiliser
 * ce chantier, jamais en recréer un second. */
class ChoixApresCreationErreur extends Error {
  constructor(cause: unknown) {
    super("chantier créé, choix échoué", { cause });
    this.name = "ChoixApresCreationErreur";
  }
}

/** Action de l'alerte « Chantier à confirmer » (R18, spec §2.4) : un
 * bouton « C'est <nom> » par candidat, plus « Autre chantier… » -- soit un
 * chantier existant (`listerChantiers`, déjà chargée par `ARegler.tsx`),
 * soit la création d'un nouveau chantier (nom, client, agence), même
 * principe qu'`AliasCarte` (fix round 1 de la revue de cette tâche : la
 * spec §2.4 exige explicitement « avec création possible », un simple
 * `<select>` ne suffisait pas). Jamais le formulaire générique Contesté/
 * Ignorer (`FormulaireTraitement`), qui n'a pas de sens ici : choisir le
 * chantier ferme l'alerte de son côté (`choisir_chantier_document`,
 * journal `chantier_choisi` + `anomalie_traitee` automatique). */
function DetailR18({
  anomalie,
  chantiers,
  onTraitementReussi,
}: {
  anomalie: Anomalie;
  chantiers: Chantier[];
  onTraitementReussi: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [autreOuvert, setAutreOuvert] = useState(false);
  const [modeCreation, setModeCreation] = useState(false);
  const [chantierChoisi, setChantierChoisi] = useState("");
  const [nom, setNom] = useState("");
  const [client, setClient] = useState("");
  const [agence, setAgence] = useState("");
  // Id du chantier créé par un essai précédent de cette même carte, quand
  // `choisirChantierDocument` a ensuite échoué (même idiome qu'`AliasCarte
  // ::chantierCreeIdRef`) : un réessai réutilise cet id au lieu d'appeler
  // `creerChantier` une seconde fois (qui échouerait, le nom existant
  // déjà). Remis à `null` dès qu'un choix réussit.
  const chantierCreeIdRef = useRef<string | null>(null);
  const candidats = candidatsR18(anomalie);
  const documentId = anomalie.document_id;

  async function apresChoixReussi(): Promise<void> {
    // Ferme l'alerte côté serveur (`choisir_chantier_document`) : mêmes
    // invalidations que tout traitement de problème
    // (`invaliderApresChangementAnomalies`), plus le référentiel chantier
    // (`document.chantier_id`, et un chantier a pu être créé, comme
    // `AliasCarte`).
    await Promise.all([
      invaliderApresChangementAnomalies(queryClient),
      queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS }),
    ]);
    onTraitementReussi();
  }

  const choix = useMutation({
    mutationFn: (chantierId: string) => choisirChantierDocument(documentId ?? "", chantierId),
    onSuccess: apresChoixReussi,
  });

  const validationAutre = useMutation({
    mutationFn: async () => {
      let chantierId: string;
      if (modeCreation) {
        if (chantierCreeIdRef.current !== null) {
          chantierId = chantierCreeIdRef.current;
        } else {
          const cree = await creerChantier(
            nom,
            agence.trim() === "" ? null : agence.trim(),
            client.trim() === "" ? null : client.trim(),
          );
          chantierCreeIdRef.current = cree.id;
          chantierId = cree.id;
        }
      } else {
        chantierId = chantierChoisi;
      }

      try {
        const resultat = await choisirChantierDocument(documentId ?? "", chantierId);
        chantierCreeIdRef.current = null;
        return resultat;
      } catch (erreur) {
        // `chantierId` existe déjà en base à ce stade (créé à cet essai ou
        // à un essai précédent) : le signaler distinctement de l'erreur
        // brute de `choisirChantierDocument`.
        if (modeCreation) {
          throw new ChoixApresCreationErreur(erreur);
        }
        throw erreur;
      }
    },
    // Que le choix réussisse ou échoue après une création de chantier, le
    // référentiel a pu changer (chantier créé) : jamais servir une liste
    // de chantiers périmée depuis le cache (même raison qu'`AliasCarte`).
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
    },
    onSuccess: apresChoixReussi,
  });

  if (documentId === null) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Bon introuvable pour ce problème.
      </p>
    );
  }

  function soumettreAutre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    validationAutre.mutate();
  }

  function messageErreurAutre(erreur: unknown): string {
    if (erreur instanceof ChoixApresCreationErreur) {
      return "Le chantier a été créé, son choix pour ce bon a échoué : réessayez.";
    }
    if (erreur instanceof ChantierEnDoubleErreur) {
      const existant = chantiers.find((chantier) => chantier.id === erreur.originalId);
      return existant ? `Le chantier « ${existant.nom_canonique} » existe déjà.` : "Ce chantier existe déjà.";
    }
    if (erreur instanceof ErreurApi) {
      return erreur.detail;
    }
    return "Une erreur est survenue, réessayez.";
  }

  const soumissionAutreValide = modeCreation ? nom.trim() !== "" : chantierChoisi !== "";
  const classesChamp =
    "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
  const classesLabel = "mb-1 block text-sm font-semibold text-encre";

  return (
    <div className="mt-auto flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        {candidats.map((candidat) => (
          <Bouton
            key={candidat.id}
            type="button"
            onClick={() => choix.mutate(candidat.id)}
            disabled={choix.isPending}
            className="w-full"
          >
            {`C'est ${candidat.nom}`}
          </Bouton>
        ))}
      </div>
      <Bouton
        type="button"
        variante="secondaire"
        onClick={() => setAutreOuvert((valeur) => !valeur)}
        className="w-full"
      >
        Autre chantier…
      </Bouton>
      {autreOuvert && (
        <form onSubmit={soumettreAutre} className="flex flex-col gap-3">
          {!modeCreation && (
            <div>
              <label htmlFor={`chantier-r18-${anomalie.id}`} className={classesLabel}>
                Chantier existant
              </label>
              <select
                id={`chantier-r18-${anomalie.id}`}
                value={chantierChoisi}
                onChange={(evenement) => setChantierChoisi(evenement.target.value)}
                className={classesChamp}
              >
                <option value="">— Choisir un chantier —</option>
                {chantiers.map((chantier) => (
                  <option key={chantier.id} value={chantier.id}>
                    {chantier.nom_canonique}
                    {chantier.agence !== null ? ` (${chantier.agence})` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          {modeCreation && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label htmlFor={`chantier-r18-nom-${anomalie.id}`} className={classesLabel}>
                  Nom du chantier
                </label>
                <input
                  id={`chantier-r18-nom-${anomalie.id}`}
                  type="text"
                  value={nom}
                  onChange={(evenement) => setNom(evenement.target.value)}
                  className={classesChamp}
                />
              </div>
              <div>
                <label htmlFor={`chantier-r18-client-${anomalie.id}`} className={classesLabel}>
                  Client
                </label>
                <input
                  id={`chantier-r18-client-${anomalie.id}`}
                  type="text"
                  value={client}
                  onChange={(evenement) => setClient(evenement.target.value)}
                  className={classesChamp}
                />
              </div>
              <div>
                <label htmlFor={`chantier-r18-agence-${anomalie.id}`} className={classesLabel}>
                  Agence
                </label>
                <input
                  id={`chantier-r18-agence-${anomalie.id}`}
                  type="text"
                  value={agence}
                  onChange={(evenement) => setAgence(evenement.target.value)}
                  className={classesChamp}
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <Bouton
              type="submit"
              disabled={!soumissionAutreValide || validationAutre.isPending}
              className="sm:flex-1"
            >
              {modeCreation ? "Créer et choisir" : "Choisir ce chantier"}
            </Bouton>
            <Bouton
              type="button"
              variante="secondaire"
              onClick={() => setModeCreation((valeur) => !valeur)}
              className="sm:flex-1"
            >
              {modeCreation ? "Choisir un chantier existant" : "Créer un chantier"}
            </Bouton>
          </div>

          {validationAutre.isError && (
            <p role="alert" className="text-sm text-alerte">
              {messageErreurAutre(validationAutre.error)}
            </p>
          )}
        </form>
      )}
      {choix.isError && (
        <p role="alert" className="text-sm text-alerte">
          {choix.error instanceof ErreurApi ? choix.error.detail : "Une erreur est survenue, réessayez."}
        </p>
      )}
    </div>
  );
}

function DetailAnomalie({
  anomalie,
  chantiers,
  onTraitementReussi,
}: {
  anomalie: Anomalie;
  chantiers: Chantier[];
  onTraitementReussi: () => void;
}): ReactElement {
  // Fix round 2, finding 1 : régression du fix round 1 (finding 6,
  // commentaire ci-dessous) -- le lien bon n'était affiché que pour une
  // anomalie dont `type !== "facture"` (R11, R15), alors que
  // `rapprochement.py:931-936` pose `document_id = facture_id` sur toutes
  // les règles pures (R01 à R09, R12, R13, R17), qui ont donc toutes
  // `type === "facture"` mais peuvent malgré tout connaître leur bon via
  // le bloc (`bl_document_id`, joint depuis `BlocFacture`,
  // `app/modules/ingest/anomalies.py::_requete_anomalies`) dès que ce
  // bloc est apparié à un BL. `cibleBon` vaut `document_id` lui-même pour
  // R11/R15/R18 (`document_id` porte déjà l'identifiant du BL, `type =
  // "bl"` -- R18 ajoutée par l'avenant du 27/09/2026, pas encore câblée
  // dans `ingest` mais dont `ChantierIncertainControle.document_id` porte
  // déjà le même document)
  // ou `bl_document_id` pour tout le reste -- y compris une anomalie de
  // facture, qui peut donc afficher les deux liens à la fois (ex. R01/R02,
  // maquette `ARegler` : « Voir la facture · Voir le bon de livraison »).
  //
  // Fix round 3, finding 1 : régression du fix round 2 ci-dessus -- la
  // condition ne testait que `anomalie.type`, jamais la présence réelle de
  // `document_id`. R06 (contrôle différé, `app/modules/ingest/suivi.py:370`,
  // `engine.py:166-169`) ne porte que `bloc_id` (`R06.py:61`, confirmé par
  // `test_suivi.py:190-194`, qui ne vérifie que `bloc_id`/`ligne_id`) --
  // `document_id` et `type` valent donc tous les deux `null` (jointure
  // externe sur `Document`, `anomalies.py:465`), alors que `bl_document_id`
  // est toujours renseigné (`suivi.py:146` n'accepte que des blocs déjà
  // reliés à un BL). Avec `null !== "facture"` vrai, `cibleBon` prenait la
  // valeur de `document_id`, donc `null` : plus aucun lien pour une R06,
  // alors que c'est justement une ligne de ce bon qui est en cause. On ne
  // retient `document_id` que lorsqu'il est réellement connu -- sinon on
  // se rabat toujours sur `bl_document_id` (R01-R09/R12/R13/R17 comme
  // avant, et désormais R06 ; R11/R15/R18 gardent `document_id`, seules
  // règles dont ce champ porte déjà l'identifiant du BL).
  const cibleBon =
    anomalie.document_id !== null && anomalie.type !== "facture" ? anomalie.document_id : anomalie.bl_document_id;
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "anomalie", id: "", anomalie }} />
        <h2 className="font-titre text-2xl font-medium text-encre">{titreRegle(anomalie.regle)}</h2>
        <p className="text-sm text-encre-2">
          {anomalie.chantier ?? CHANTIER_A_RATTACHER} · {anomalie.fournisseur ?? TIRET}
          {anomalie.numero_bl !== null ? ` · ${anomalie.numero_bl}` : ""}
        </p>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-bordure bg-fond p-4">
        <p className="text-sm font-semibold text-encre-2">Pourquoi c'est signalé</p>
        <p className="text-sm text-encre">{phraseProbleme(anomalie)}</p>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {chiffresProbleme(anomalie).map((chiffre) => (
            <div key={chiffre.libelle}>
              <dt className="text-xs text-encre-2">{chiffre.libelle}</dt>
              <dd className={`font-mono text-lg ${chiffre.ton !== undefined ? CLASSES_TON[chiffre.ton] : "text-encre"}`}>
                {chiffre.valeur}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Avis de l'IA (T7, phase 4 IA, spec §6.4) : seulement pour un
          problème de catégorie « prix » -- même critère que celui déjà
          utilisé par `Kicker` pour la catégorie affichée, sous la phrase
          du problème ci-dessus. `AvisIA` reste `null` de lui-même tant que
          l'IA n'a rien produit ou en cas d'erreur (bonus, jamais un
          blocage) : rien ne distingue donc cette ligne d'un composant qui
          ne se serait pas monté pour les autres catégories. */}
      {categorieFiltreProbleme({ kind: "anomalie", id: "", anomalie }) === "prix" && (
        <AvisIA anomalieId={anomalie.id} />
      )}

      {/* Lien facture : seulement pour une anomalie dont le document résolu
          par `document_id` est bien une facture (`type === "facture"`) —
          jamais pour R11/R15/R18, dont `document_id` porte l'identifiant du
          BL lui-même (`type = "bl"`). Dépend de la Task 8 tant qu'elle n'est
          pas fusionnée (`/documents/:id` refuse une facture,
          `_document_pour_lecture`, `app/modules/ingest/corrections.py`).
          Lien bon : voir `cibleBon` ci-dessus (fix round 2 finding 1, affiné
          au fix round 3 finding 1 pour R06) — jamais conditionné par
          `anomalie.type` à cet endroit, les deux liens peuvent s'afficher
          ensemble. Revue finale (constat LIENS-13) : « Voir la facture »
          ouvre la facture directement sur la livraison concernée (ancre
          `/documents/:id#…`, une facture réelle en compte 28). */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        {anomalie.type === "facture" && anomalie.document_id !== null && (
          <Link to={lienFacture(anomalie.document_id, anomalie.bloc_id)} className={CLASSES_LIEN}>
            Voir la facture
          </Link>
        )}
        {cibleBon !== null && (
          <Link to={`/bl/${cibleBon}`} className={CLASSES_LIEN}>
            Voir le bon de livraison
          </Link>
        )}
        {/* Phase 3, tâche P9 (spec §8.3) : une alerte de prix (R19-R25,
            catégorie « prix ») ouvre aussi la page « Prix à vérifier », qui
            regroupe l'ensemble des bons du même produit -- jamais affiché
            pour une autre catégorie. */}
        {anomalie.categorie === "prix" && (
          <Link to="/prix" className={CLASSES_LIEN}>
            Voir sur la page Prix
          </Link>
        )}
      </div>

      {anomalie.regle === "R18" ? (
        <DetailR18 anomalie={anomalie} chantiers={chantiers} onTraitementReussi={onTraitementReussi} />
      ) : (
        <FormulaireTraitement anomalie={anomalie} onTraitementReussi={onTraitementReussi} />
      )}
    </>
  );
}

/** `type` d'un document « à vérifier » (BL, enlèvement ou facture) —
 * présentation uniquement, même principe que `libelleTypeDocument` de
 * `DocumentDetail.tsx` (dupliqué, décision du contrôleur, même convention
 * que les autres petits assistants de présentation de ce fichier). Restauré
 * ici (fix round 1, finding 5) : perdu lors de la migration depuis l'ancien
 * `ATraiter.tsx::DocumentCarte`, qui l'affichait déjà à côté du n°
 * interne. */
function libelleTypeDocument(type: string): string {
  switch (type) {
    case "bl":
      return "Livraison";
    case "enlevement":
      return "Enlèvement";
    case "facture":
      return "Facture";
    default:
      return type;
  }
}

/** Lien de correction d'un document « à vérifier » (fix round 1, finding
 * 5) : une facture s'ouvre sur son détail (`/documents/:id`, revue finale,
 * constat LIENS-10 — plus l'ancienne adresse des factures et sa
 * redirection) ; un bon s'ouvre directement sur sa section de correction
 * (`#corriger`, dépliée par la page du bon — constat COUVERTURE-17). */
function cheminCorrectionDocument(document: DocumentATraiter): string {
  return document.type === "facture" ? `/documents/${document.id}` : `${lienBon(document.id)}#corriger`;
}

function DetailDocument({ document }: { document: DocumentATraiter }): ReactElement {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "document", id: "", document }} />
        <h2 className="font-titre text-2xl font-medium text-encre">{titreDocument(document)}</h2>
        <p className="text-sm text-encre-2">
          Document n° {document.numero_interne} · {libelleTypeDocument(document.type)}
        </p>
        <p className="text-sm text-encre-2">
          {document.chantier_brut ?? TIRET} · {document.fournisseur ?? TIRET} · {document.numero ?? TIRET}
        </p>
      </div>

      {document.confirmation === "ecart" && (
        // Fix round 1, finding 5(b) : un bon passe `a_verifier` quand
        // l'équipe clique « Écart constaté » sur Telegram (`ingest/
        // depot_telegram.py`), souvent sans motif — ce signalement de
        // l'équipe ne doit jamais disparaître derrière un générique « bon
        // illisible » (perdu par la migration depuis l'ancien
        // `ATraiter.tsx::BadgeEcart`).
        <p className="rounded-lg border border-bordure bg-fond p-3 text-sm text-encre">
          Écart constaté par l'équipe au dépôt — à vérifier avant traitement.
        </p>
      )}

      {document.motifs.length > 0 && (
        <div className="flex flex-col gap-2 rounded-lg border border-bordure bg-fond p-4">
          <p className="text-sm font-semibold text-encre-2">Pourquoi c'est signalé</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-encre">
            {document.motifs.map((motif, index) => (
              // Aucun identifiant stable côté API pour un motif (même
              // convention que l'ancien `ATraiter.tsx::MotifsListe`).
              <li key={index}>{libelleMotif(motif)}</li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-sm text-encre-2">
        Déposé par {document.deposant ?? TIRET} le {formaterDateHeure(document.cree_le)}.
      </p>

      <LienPrincipal to={cheminCorrectionDocument(document)}>
        {document.type === "facture" ? "Voir la facture" : "Corriger le bon"}
      </LienPrincipal>
    </>
  );
}

function DetailAlias({
  alias,
  chantiers,
  onTraitementReussi,
}: {
  alias: AliasEnAttente;
  chantiers: Chantier[];
  onTraitementReussi: () => void;
}): ReactElement {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "alias", id: "", alias }} />
        <h2 className="font-titre text-2xl font-medium text-encre">Chantier à rattacher</h2>
        <p className="text-sm text-encre-2">
          {alias.fournisseur} · {alias.nb_documents} document{alias.nb_documents > 1 ? "s" : ""}
        </p>
      </div>
      {/* Revue finale (constat LIENS-11) : un rattachement réussi passe au
          problème suivant, comme un problème traité. */}
      <AliasCarte alias={alias} chantiers={chantiers} onReussite={onTraitementReussi} />
    </>
  );
}

function DetailArticle({
  article,
  onTraitementReussi,
}: {
  article: ArticleAValider;
  onTraitementReussi: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [uniteCdt, setUniteCdt] = useState(article.unite_cdt ?? "");
  const [uniteFact, setUniteFact] = useState(article.unite_fact ?? "");
  const [ratio, setRatio] = useState(article.ratio ?? "");

  const validation = useMutation({
    mutationFn: () =>
      validerArticle(article.id, {
        uniteCdt: uniteCdt.trim() === "" ? null : uniteCdt.trim(),
        uniteFact: uniteFact.trim() === "" ? null : uniteFact.trim(),
        ratio: ratio.trim() === "" ? null : ratio.trim().replace(",", "."),
      }),
    onSuccess: async () => {
      // Un article validé quitte la liste « À régler » : son compte unique
      // (pastille, vue d'ensemble) est invalidé avec le reste.
      await Promise.all([
        invaliderApresChangementAnomalies(queryClient),
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS }),
      ]);
      // Revue finale (constat LIENS-11) : comme un problème traité, un
      // article validé passe au problème suivant — plus jamais le message
      // « Ce problème n'est plus disponible » juste après sa propre action.
      onTraitementReussi();
    },
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    validation.mutate();
  }

  const classesChamp =
    "w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
  const classesLabel = "mb-1 block text-sm font-semibold text-encre";

  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "article", id: "", article }} />
        <h2 className="font-titre text-2xl font-medium text-encre">Article à valider</h2>
        <p className="text-sm text-encre-2">
          {article.fournisseur} · {article.code}
          {article.libelle !== null ? ` · ${article.libelle}` : ""}
        </p>
      </div>

      <form onSubmit={soumettre} className="flex flex-col gap-3">
        <div>
          <label htmlFor={`unite-cdt-${article.id}`} className={classesLabel}>
            Unité de conditionnement
          </label>
          <input
            id={`unite-cdt-${article.id}`}
            type="text"
            value={uniteCdt}
            onChange={(evenement) => setUniteCdt(evenement.target.value)}
            className={classesChamp}
          />
        </div>
        <div>
          <label htmlFor={`unite-fact-${article.id}`} className={classesLabel}>
            Unité de facturation
          </label>
          <input
            id={`unite-fact-${article.id}`}
            type="text"
            value={uniteFact}
            onChange={(evenement) => setUniteFact(evenement.target.value)}
            className={classesChamp}
          />
        </div>
        <div>
          <label htmlFor={`ratio-${article.id}`} className={classesLabel}>
            Ratio
          </label>
          <input
            id={`ratio-${article.id}`}
            type="text"
            inputMode="decimal"
            value={ratio}
            onChange={(evenement) => setRatio(evenement.target.value)}
            className={classesChamp}
          />
        </div>
        <Bouton type="submit" disabled={validation.isPending} className="mt-auto">
          Valider
        </Bouton>
        {validation.isError && (
          <p role="alert" className="text-sm text-alerte">
            {validation.error instanceof ErreurApi ? validation.error.detail : "Une erreur est survenue, réessayez."}
          </p>
        )}
      </form>
    </>
  );
}

/** Section « Nouveaux chantiers à compléter » (spec §2.6) : le panneau ne
 * propose ici qu'un lien vers la fiche du chantier (`LienPrincipal`, même
 * navigation réelle que « Corriger le bon ») -- compléter la fiche
 * (agence, client) et sortir de cette liste se fait sur l'écran
 * « Chantiers », jamais ici (aucune règle métier dans ce panneau). */
function DetailChantierACompleter({ chantier }: { chantier: ChantierACompleter }): ReactElement {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "chantier", id: "", chantier }} />
        <h2 className="font-titre text-2xl font-medium text-encre">{chantier.nom}</h2>
        <p className="text-sm text-encre-2">
          Créé automatiquement le {formaterDateHeure(chantier.cree_le)} · {chantier.nb_bons} bon
          {chantier.nb_bons > 1 ? "s" : ""}
        </p>
      </div>

      <p className="text-sm text-encre-2">
        Ce chantier a été créé automatiquement à partir d'un nom lu sur un bon, sans agence ni client renseignés.
        Complétez sa fiche pour qu'il ne soit plus « à compléter ».
      </p>

      <LienPrincipal to={`/chantiers/${chantier.id}`}>Compléter</LienPrincipal>
    </>
  );
}

export function ProblemeDetail({
  probleme,
  chantiers,
  lienRetour,
  onTraitementReussi,
}: {
  probleme: Probleme;
  chantiers: Chantier[];
  lienRetour: string;
  onTraitementReussi: () => void;
}): ReactElement {
  return (
    // `h-full` retiré (fix round 1, finding 7) : étirait ce panneau à la
    // hauteur de la cellule de grille (celle de la liste, souvent bien
    // plus grande), poussant le commentaire et les boutons de traitement
    // hors de la fenêtre. `ARegler.tsx` rend désormais l'`<aside>` parent
    // `lg:sticky`/`lg:max-h-*` avec défilement interne — cette carte se
    // dimensionne à son propre contenu à l'intérieur.
    <Carte className="flex flex-col gap-5">
      <Link to={lienRetour} className={`${CLASSES_LIEN} text-sm lg:hidden`}>
        ← Retour à la liste
      </Link>
      {probleme.kind === "anomalie" && (
        <DetailAnomalie anomalie={probleme.anomalie} chantiers={chantiers} onTraitementReussi={onTraitementReussi} />
      )}
      {probleme.kind === "document" && <DetailDocument document={probleme.document} />}
      {probleme.kind === "chantier" && <DetailChantierACompleter chantier={probleme.chantier} />}
      {probleme.kind === "alias" && (
        <DetailAlias alias={probleme.alias} chantiers={chantiers} onTraitementReussi={onTraitementReussi} />
      )}
      {probleme.kind === "article" && (
        <DetailArticle article={probleme.article} onTraitementReussi={onTraitementReussi} />
      )}
    </Carte>
  );
}
