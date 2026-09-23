import { type FormEvent, type ReactElement, type ReactNode, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  type AliasEnAttente,
  type ArticleAValider,
  CLE_A_TRAITER,
  type DocumentATraiter,
} from "../api/aTraiter";
import { type Anomalie, CLE_ANOMALIES, traiterAnomalie } from "../api/anomalies";
import { ErreurApi } from "../api/client";
import { type Chantier, CLE_CHANTIERS, validerArticle } from "../api/referentiels";
import { CLE_TABLEAU_DE_BORD } from "../api/tableauDeBord";
import { AliasCarte } from "../components/AliasCarte";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";
import { Bouton, Carte, phraseProbleme, titreRegle, type TonChiffre, urgence } from "../ui";
import {
  categorieFiltreProbleme,
  dateHeureOuTiret,
  dateOuTiret,
  montantOuTiret,
  pointsOuAucun,
  pointsOuTiret,
  type Probleme,
  quantiteOuTiret,
  texteOuTiret,
  titreDocument,
  type Urgence,
} from "./ARegler";

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

const CLASSES_TON: Record<TonChiffre, string> = {
  neutre: "text-encre",
  conforme: "text-conforme",
  ecart: "text-ecart-texte",
  alerte: "text-alerte",
};

interface ChiffreProbleme {
  libelle: string;
  valeur: string;
  ton?: TonChiffre;
}

/** 2 à 3 valeurs chiffrées nommées justifiant l'anomalie (brief Task 6),
 * tirées de `detail` sans aucun calcul (mêmes clés que `phraseProbleme`,
 * `web/src/ui/libelles.ts`) — pas ajoutée à ce fichier partagé (règle
 * globale de la refonte : ne pas modifier `web/src/ui/`, sans exception
 * pour `libelles.ts`), donc réimplémentée ici avec les mêmes garanties
 * défensives (`montantOuTiret`/`quantiteOuTiret`/… d'`ARegler.tsx`). Voir
 * le rapport de tâche pour cette décision. */
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
    default:
      return Object.entries(detail).map(([cle, valeur]) => ({ libelle: cle, valeur }));
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
      // gabarit incluse, même préfixe de clé), tableau de bord, bilan.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_ANOMALIES }),
        queryClient.invalidateQueries({ queryKey: CLE_TABLEAU_DE_BORD }),
        queryClient.invalidateQueries({ queryKey: ["bilan"] }),
      ]);
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

function DetailAnomalie({
  anomalie,
  onTraitementReussi,
}: {
  anomalie: Anomalie;
  onTraitementReussi: () => void;
}): ReactElement {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "anomalie", id: "", anomalie }} />
        <h2 className="font-titre text-2xl font-medium text-encre">{titreRegle(anomalie.regle)}</h2>
        <p className="text-sm text-encre-2">
          {anomalie.chantier ?? TIRET} · {anomalie.fournisseur ?? TIRET}
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

      {/* Fix round 1, finding 6 : « Voir la facture » s'affichait pour
          toute anomalie avec un `document_id`, sans regarder son type —
          pour les règles portées par un BL (R11, R15 : `document_id` porte
          l'identifiant du BL lui-même, `type = "bl"`), le seul lien
          affiché s'appelait « Voir la facture » et ouvrait pourtant le bon
          de livraison. `anomalie.type` (le type du document résolu par
          `document_id`, `app/modules/ingest/anomalies.py::_anomalie_lue`)
          tranche désormais laquelle des deux étiquettes est correcte,
          jamais les deux à la fois sur un même document : une facture
          (`type === "facture"`, ex. R10) vers `/documents/:id` (dépend de
          la Task 8 tant qu'elle n'est pas fusionnée, `_document_pour_
          lecture` refuse une facture, `app/modules/ingest/corrections.py`)
          ; sinon `document_id` est déjà un bon de livraison (R11, R15) et
          `bl_document_id` (résolu via le bloc, R01/R02/R06…) n'est utilisé
          qu'en second recours. */}
      <div className="flex flex-wrap gap-3 text-sm">
        {anomalie.type === "facture" && anomalie.document_id !== null && (
          <Link
            to={`/documents/${anomalie.document_id}`}
            className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Voir la facture
          </Link>
        )}
        {anomalie.type !== "facture" && anomalie.document_id !== null && (
          <Link
            to={`/bl/${anomalie.document_id}`}
            className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Voir le bon de livraison
          </Link>
        )}
        {anomalie.type !== "facture" && anomalie.document_id === null && anomalie.bl_document_id !== null && (
          <Link
            to={`/bl/${anomalie.bl_document_id}`}
            className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Voir le bon de livraison
          </Link>
        )}
      </div>

      <FormulaireTraitement anomalie={anomalie} onTraitementReussi={onTraitementReussi} />
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

/** Lien et libellé de correction d'un document « à vérifier » (fix round
 * 1, finding 5) : une facture n'a pas de section de correction sur `/bl/:id`
 * (route réservée au BL/enlèvement, `_document_pour_lecture`,
 * `app/modules/ingest/corrections.py`) — elle renvoie vers `/factures/:id`
 * (écran existant, `FactureDetail.tsx`, toujours monté tant que la Task 8
 * ne l'a pas remplacé par `/documents/:id`, voir le rapport de tâche). */
function cheminCorrectionDocument(document: DocumentATraiter): string {
  return document.type === "facture" ? `/factures/${document.id}` : `/bl/${document.id}`;
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

function DetailAlias({ alias, chantiers }: { alias: AliasEnAttente; chantiers: Chantier[] }): ReactElement {
  return (
    <>
      <div className="flex flex-col gap-1">
        <Kicker probleme={{ kind: "alias", id: "", alias }} />
        <h2 className="font-titre text-2xl font-medium text-encre">Chantier à rattacher</h2>
        <p className="text-sm text-encre-2">
          {alias.fournisseur} · {alias.nb_documents} document{alias.nb_documents > 1 ? "s" : ""}
        </p>
      </div>
      <ul className="list-none">
        <AliasCarte alias={alias} chantiers={chantiers} />
      </ul>
    </>
  );
}

function DetailArticle({ article }: { article: ArticleAValider }): ReactElement {
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER }),
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS }),
      ]);
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
      <Link
        to={lienRetour}
        className="text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent lg:hidden"
      >
        ← Retour à la liste
      </Link>
      {probleme.kind === "anomalie" && (
        <DetailAnomalie anomalie={probleme.anomalie} onTraitementReussi={onTraitementReussi} />
      )}
      {probleme.kind === "document" && <DetailDocument document={probleme.document} />}
      {probleme.kind === "alias" && <DetailAlias alias={probleme.alias} chantiers={chantiers} />}
      {probleme.kind === "article" && <DetailArticle article={probleme.article} />}
    </Carte>
  );
}
