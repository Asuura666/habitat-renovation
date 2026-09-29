import { Fragment, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  type AlerteProduit,
  CLE_ALERTES_PRIX,
  cleAlertesPrix,
  contesterPrix,
  ignorerPrix,
  listerAlertesPrix,
  type PeriodeAlertesPrix,
  recontrolerPrix,
  validerPrix,
} from "../api/prix";
import { ErreurApi } from "../api/client";
import { clePrixInternet, lirePrixInternet, type PrixInternet } from "../api/ia";
import { invaliderApresChangementAnomalies } from "../api/invalidations";
import { CLE_PARAMETRES, listerParametres } from "../api/parametres";
import { CLE_FOURNISSEURS, listerFournisseurs } from "../api/referentiels";
import { PrixInternetCellule } from "../components/PrixInternetCellule";
import { gererEntreeCommentaire } from "../lib/entreeClavier";
import { formaterDate, formaterMontant, formaterPoints, TIRET } from "../lib/formats";
import { lienBon } from "../lib/liens";
import { Bouton, Carte, EnTetePage, EtatVide, Filtres, type OptionFiltre, titreRegle } from "../ui";

/** Plafond de `GET /api/ia/prix-internet` (`MAX_ANOMALIES_PRIX_INTERNET`,
 * `ingest/ia_prix.py`, 422 au-delà) -- défense côté front, jamais atteinte
 * en pratique (nombre de rangées R22 affichées en même temps très en-deçà),
 * mais évite de jamais provoquer ce 422 si la liste explosait un jour. */
const MAX_IDS_PRIX_INTERNET = 200;

/** Identifiants d'anomalies à interroger pour une rangée (fix round 1,
 * ruling du contrôleur : le brief T10b disait « le premier de
 * `anomalie_ids` », mais `regles` et `anomalie_ids` sont deux tableaux
 * indépendants -- R22 peut cohabiter avec R20/R24 sur la même ligne
 * (`rules/rules/R22.py` : seules ces deux règles peuvent encore se
 * déclencher sur une ligne déjà en R22) et une rangée peut grouper
 * plusieurs lignes, donc `anomalie_ids[0]` n'est pas forcément celui de
 * R22. Tableau vide si la rangée n'a pas d'alerte R22 (exclue de la requête
 * groupée, cellule à tiret) -- tous les identifiants sinon, la réponse ne
 * portant de toute façon jamais de clé pour un identifiant qui ne désigne
 * pas une alerte R22 ouverte et non masquée (brief T10a). */
function idsInternetPour(produit: AlerteProduit): readonly string[] {
  return produit.regles.includes("R22") ? produit.anomalie_ids : [];
}

/** Réglage qui commande l'écran tout entier (spec §3.4, §8.3) -- toujours
 * présent dans `GET /api/parametres` (interrupteur général « toujours
 * visible », jamais masqué comme les réglages propres à un contrôle déjà
 * désactivé). */
const CLE_INTERRUPTEUR_GENERAL = "prix_controle_bl_actif";

const CLASSES_CHAMP =
  "min-h-[44px] rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";

function messageErreur(erreur: unknown, repli: string): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return repli;
}

function accorder(nombre: number, singulier: string, pluriel: string): string {
  return nombre > 1 ? pluriel : singulier;
}

/** Identifie un groupe de la liste : les alertes d'un même produit
 * partagent le même ensemble d'identifiants d'alertes (`AlerteProduit.
 * anomalie_ids`, spec §8.1), stable tant que la liste n'est pas
 * rechargée. */
function cleProduit(produit: AlerteProduit): string {
  return produit.anomalie_ids.join(",");
}

/** Prix de la grille (spec §8.1) : « absent de la grille » seulement quand
 * R22 est présente pour ce groupe (aucun produit retrouvé dans la grille).
 * Un groupe dont la seule alerte de grille est R24 (unités différentes) a
 * un produit de la grille, simplement non comparable : afficher son unité
 * plutôt que de prétendre qu'il est absent (constat front, tour 2). Les
 * autres cas sans prix comparable (ex. seule R20 déclenchée, sans info de
 * grille du tout) affichent le tiret. */
function texteGrille(produit: AlerteProduit): string {
  if (produit.prix_grille !== null) {
    const unite = produit.unite_grille ? ` ${produit.unite_grille}` : "";
    const date = produit.date_grille ? ` (${formaterDate(produit.date_grille)})` : "";
    const posterieure = produit.grille_posterieure_au_bon ? " -- grille postérieure au bon" : "";
    return `${formaterMontant(produit.prix_grille)}${unite}${date}${posterieure}`;
  }
  if (produit.regles.includes("R22")) {
    return "Absent de la grille";
  }
  if (produit.unite_grille_non_comparable !== null) {
    return `Unité différente (${produit.unite_grille_non_comparable})`;
  }
  return TIRET;
}

function texteDernierPrix(produit: AlerteProduit): string {
  if (produit.dernier_prix === null) {
    return TIRET;
  }
  const unite = produit.unite_dernier_prix ? ` ${produit.unite_dernier_prix}` : "";
  const date = produit.date_dernier_prix ? ` (${formaterDate(produit.date_dernier_prix)})` : "";
  return `${formaterMontant(produit.dernier_prix)}${unite}${date}`;
}

/** « Par référence » ou « 83 % » (spec §8.1) -- `null` si aucune alerte de
 * correspondance (R22 seule, produit jamais retrouvé dans la grille).
 * `methode` n'est pas toujours connu même quand `ressemblance` l'est : R23
 * et R25 (`rules/rules/R23.py`, `R25.py`) ne portent pas cette clé dans
 * leur `detail` (spec §5.2, table des clés) -- un groupe dont la seule
 * alerte de grille est R23 a donc `methode === null` avec un `ressemblance`
 * renseigné, jamais l'inverse (la référence n'est jamais mêlée à une
 * correspondance par nom). */
function texteRessemblance(produit: AlerteProduit): string | null {
  if (produit.methode === "reference") {
    return "Par référence";
  }
  return produit.ressemblance !== null ? `ressemblance : ${produit.ressemblance} %` : null;
}

/** Écart avec sa flèche (spec §8.1) : la flèche porte déjà le sens, la
 * valeur affichée est donc la valeur absolue (signe explicite `+` pour une
 * hausse, aucun signe redondant avec la flèche pour une baisse) -- `ui/
 * libelles.ts` n'affiche que le signe, sans flèche, pour le texte des
 * phrases (cas R19/R21), ce n'est pas la même convention. */
function texteEcart(produit: AlerteProduit): string | null {
  if (produit.ecart_pct === null) {
    return null;
  }
  const valeur = Number(produit.ecart_pct);
  const fleche = valeur > 0 ? "↑ " : valeur < 0 ? "↓ " : "";
  const signe = valeur > 0 ? "+" : "";
  return `${fleche}${signe}${formaterPoints(String(Math.abs(valeur)))}`;
}

interface PrixBon {
  /** Le prix et son unité, en police à chasse fixe. */
  prix: string;
  /** « sur 3 bons, 3 prix différents » -- `null` s'il n'y a qu'un bon et un
   * seul prix. Affiché à part, en texte courant (spec §8.1 point 2) : dans
   * la police à chasse fixe du prix, cette phrase se cassait mot par mot au
   * lieu de rester lisible (constat capture, tour 2). */
  complement: string | null;
}

function texteBon(produit: AlerteProduit): PrixBon {
  const unite = produit.unite_bon ? ` ${produit.unite_bon}` : "";
  const mentions: string[] = [];
  if (produit.nb_bons > 1) {
    mentions.push(`sur ${produit.nb_bons} bons`);
  }
  if (produit.nb_prix_differents > 1) {
    mentions.push(`${produit.nb_prix_differents} prix différents`);
  }
  return {
    prix: `${formaterMontant(produit.prix_bon)}${unite}`,
    complement: mentions.length > 0 ? mentions.join(", ") : null,
  };
}

/** Rendu commun du prix du bon (carte et tableau, spec §8.1 point 2). */
function PrixBonAffiche({ produit }: { produit: AlerteProduit }): ReactElement {
  const bon = texteBon(produit);
  return (
    <>
      <span className="font-mono">{bon.prix}</span>
      {bon.complement !== null && <p className="mt-0.5 text-xs font-normal text-encre-2">{bon.complement}</p>}
    </>
  );
}

/** Code et fournisseur, sous le nom du produit (spec §8.1) : sans code, un
 * tiret suivi du fournisseur (« — · Fournisseur ») ne dit rien d'utile --
 * le libellé combiné « Sans référence · Fournisseur » ne s'utilise nulle
 * part ailleurs dans l'application (seul `GrilleFournisseur.tsx` affiche
 * « Sans référence », seul), donc ici seul le fournisseur reste affiché
 * (constat front, tour 2). */
function texteCodeFournisseur(produit: AlerteProduit): string {
  return produit.code !== null ? `${produit.code} · ${produit.fournisseur}` : produit.fournisseur;
}

function texteAlertes(produit: AlerteProduit): string {
  return produit.regles.map((regle) => titreRegle(regle)).join(" · ");
}

interface ActionsProps {
  produit: AlerteProduit;
  panneauOuvert: "contester" | "ignorer" | null;
  commentaire: string;
  enCours: boolean;
  erreur: string | null;
  onOuvrirPanneau: (type: "contester" | "ignorer") => void;
  onFermerPanneau: () => void;
  onCommentaireChange: (valeur: string) => void;
  onValider: () => void;
  onConfirmerPanneau: () => void;
}

/** Les trois actions de chaque rangée (spec §8.2, §8.3) : « Valider ce
 * prix » agit tout de suite, « Contester »/« Ignorer » ouvrent une zone de
 * commentaire sur place plutôt que de fermer l'alerte au premier clic. */
function ActionsAlertePrix({
  produit,
  panneauOuvert,
  commentaire,
  enCours,
  erreur,
  onOuvrirPanneau,
  onFermerPanneau,
  onCommentaireChange,
  onValider,
  onConfirmerPanneau,
}: ActionsProps): ReactElement {
  const commentaireVide = commentaire.trim() === "";
  const confirmationPossible = !enCours && !(panneauOuvert === "contester" && commentaireVide);

  /** Entrée sur ordinateur (`lib/entreeClavier.ts`) : mêmes conditions que
   * le bouton « Contester »/« Ignorer » du panneau. */
  function confirmerAuClavier(): void {
    if (confirmationPossible) {
      onConfirmerPanneau();
    }
  }
  return (
    <div className="flex flex-col gap-2">
      {panneauOuvert === null && (
        <div className="flex flex-wrap gap-2">
          <Bouton className="whitespace-nowrap" onClick={onValider} disabled={enCours}>
            {enCours ? "En cours…" : "Valider ce prix"}
          </Bouton>
          <Bouton
            className="whitespace-nowrap"
            variante="secondaire"
            onClick={() => onOuvrirPanneau("contester")}
            disabled={enCours}
          >
            Contester
          </Bouton>
          <Bouton
            className="whitespace-nowrap"
            variante="secondaire"
            onClick={() => onOuvrirPanneau("ignorer")}
            disabled={enCours}
          >
            Ignorer
          </Bouton>
        </div>
      )}
      {panneauOuvert !== null && (
        <div className="flex flex-col gap-2 rounded-lg border border-bordure bg-fond p-3">
          <label htmlFor={`commentaire-${cleProduit(produit)}`} className="text-xs font-medium text-encre">
            {panneauOuvert === "contester" ? "Commentaire (obligatoire)" : "Commentaire (facultatif)"}
          </label>
          <textarea
            id={`commentaire-${cleProduit(produit)}`}
            value={commentaire}
            onChange={(e) => onCommentaireChange(e.target.value)}
            onKeyDown={(e) => gererEntreeCommentaire(e, confirmerAuClavier, onCommentaireChange)}
            rows={2}
            maxLength={500}
            className="w-full resize-none rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          <p className="hidden text-xs text-encre-2 [@media(hover:hover)_and_(pointer:fine)]:block">
            Entrée pour valider, Maj+Entrée pour aller à la ligne
          </p>
          <div className="flex flex-wrap gap-2">
            <Bouton
              onClick={onConfirmerPanneau}
              disabled={!confirmationPossible}
            >
              {enCours ? "En cours…" : panneauOuvert === "contester" ? "Contester" : "Ignorer"}
            </Bouton>
            <Bouton variante="secondaire" onClick={onFermerPanneau} disabled={enCours}>
              Annuler
            </Bouton>
          </div>
        </div>
      )}
      {erreur !== null && (
        <p role="alert" className="text-sm text-alerte">
          {erreur}
        </p>
      )}
    </div>
  );
}

/** Une rangée de la page, en carte (téléphone) — mêmes informations que le
 * tableau ci-dessous (spec §8.1, §8.3), plus la colonne « Internet » (T10b,
 * phase 4 IA) au même endroit qu'au tableau : juste après « Dernier prix
 * facturé », seulement quand l'IA est active (`colonneInternetVisible`,
 * calculé par `Prix()` -- jamais relu ici). */
function CarteAlertePrix({
  produit,
  actions,
  colonneInternetVisible,
  prixInternet,
}: {
  produit: AlerteProduit;
  actions: ReactElement;
  colonneInternetVisible: boolean;
  prixInternet: PrixInternet | null | undefined;
}): ReactElement {
  const ressemblance = texteRessemblance(produit);
  return (
    <li className="rounded-carte border border-bordure bg-surface p-4">
      <p className="font-medium text-encre">{produit.produit}</p>
      <p className="text-sm text-encre-2">
        {texteCodeFournisseur(produit)}
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Prix du bon</dt>
          <dd className="text-encre">
            <PrixBonAffiche produit={produit} />
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Grille</dt>
          <dd className="text-encre">{texteGrille(produit)}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Dernier prix facturé</dt>
          <dd className="text-encre">{texteDernierPrix(produit)}</dd>
        </div>
        {colonneInternetVisible && (
          <div>
            <dt className="text-xs text-encre-2">Internet</dt>
            <dd className="text-encre">
              <PrixInternetCellule produit={produit} prixInternet={prixInternet} />
            </dd>
          </div>
        )}
        <div>
          <dt className="text-xs text-encre-2">Écart</dt>
          <dd className="font-mono font-medium text-encre">
            {texteEcart(produit) ?? TIRET}
            {ressemblance !== null && <span className="ml-1 text-xs text-encre-2">({ressemblance})</span>}
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-sm text-encre">{texteAlertes(produit)}</p>
      <Link
        to={lienBon(produit.document_id)}
        className="mt-1 inline-flex min-h-[44px] items-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        Voir le bon
      </Link>
      <div className="mt-3">{actions}</div>
    </li>
  );
}

interface FiltresPrix {
  periode: PeriodeAlertesPrix;
  fournisseurId: string;
}

/**
 * Écran « Prix à vérifier » (`/prix`, phase 3, tâche P9, spec §8.3) : liste
 * des produits en alerte de prix (`GET /api/prix/alertes`), filtres
 * « Aujourd'hui »/« Tout » et fournisseur, bouton « Recontrôler les bons »,
 * trois actions par rangée. Admin seulement (`GardeAdmin`, `App.tsx`) --
 * comme les routes de l'API (`admin_requis`, `api/prix.py`). Aucun code de
 * règle ni mot technique affiché (`titreRegle`, `ui/libelles.ts`).
 */
export function Prix(): ReactElement {
  const queryClient = useQueryClient();
  const [filtres, setFiltres] = useState<FiltresPrix>({ periode: "tout", fournisseurId: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [panneau, setPanneau] = useState<{ cle: string; type: "contester" | "ignorer" } | null>(null);
  const [commentaire, setCommentaire] = useState("");

  const parametres = useQuery({ queryKey: CLE_PARAMETRES, queryFn: listerParametres });
  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });

  const controleActif =
    parametres.data?.find((p) => p.cle === CLE_INTERRUPTEUR_GENERAL)?.valeur === "1";

  const alertes = useQuery({
    queryKey: cleAlertesPrix(filtres.periode, filtres.fournisseurId),
    queryFn: () =>
      listerAlertesPrix({
        periode: filtres.periode,
        fournisseurId: filtres.fournisseurId || undefined,
      }),
    enabled: controleActif,
  });

  /** Colonne « Internet » (T10b, phase 4 IA, spec §6.4) : requête groupée,
   * tous les identifiants des rangées R22 (fix round 1, `idsInternetPour`
   * ci-dessus), dédupliqués en gardant l'ordre de la page (`Set` préserve
   * l'ordre d'insertion en JavaScript) et plafonnés à `MAX_IDS_PRIX_
   * INTERNET` au total -- activée seulement quand la liste des alertes est
   * chargée, non vide, et en contient au moins un -- aucune requête sinon.
   * Si l'IA est éteinte, si la requête échoue ou pendant son chargement :
   * `colonneInternetVisible` reste faux et rien ne change (la page reste à
   * 6 colonnes, aucun message, brief T10b). */
  const alertesChargees = alertes.data !== undefined && alertes.data.length > 0;
  const idsR22 = alertesChargees
    ? Array.from(new Set(alertes.data.flatMap((produit) => idsInternetPour(produit)))).slice(
        0,
        MAX_IDS_PRIX_INTERNET,
      )
    : [];

  const prixInternetLot = useQuery({
    queryKey: clePrixInternet(idsR22),
    queryFn: () => lirePrixInternet(idsR22),
    enabled: alertesChargees && idsR22.length > 0,
  });

  const colonneInternetVisible = prixInternetLot.data?.ia_active === true;

  /** Prix internet d'une rangée (fix round 1) : le premier des identifiants
   * de la rangée qui est présent **comme clé** de la réponse groupée --
   * jamais `anomalie_ids[0]` (voir `idsInternetPour` ci-dessus), et jamais
   * uniquement une valeur non nulle (une clé présente avec une valeur
   * `null`, « recherché sans résultat récent », doit arrêter la recherche
   * là, pas continuer vers un identifiant suivant qui n'a pas de sens pour
   * cette rangée). Aucune clé trouvée (rangée sans R22, ou au-delà du
   * plafond) -> `undefined`, même « en attente » que `null` côté cellule. */
  function prixInternetPour(produit: AlerteProduit): PrixInternet | null | undefined {
    const prix = prixInternetLot.data?.prix;
    if (prix === undefined) {
      return undefined;
    }
    const idConnu = produit.anomalie_ids.find((id) => id in prix);
    return idConnu === undefined ? undefined : prix[idConnu];
  }

  async function apresAction(texte: string): Promise<void> {
    setPanneau(null);
    setCommentaire("");
    setMessage(texte);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: CLE_ALERTES_PRIX }),
      invaliderApresChangementAnomalies(queryClient),
    ]);
  }

  const validerMutation = useMutation({
    mutationFn: (produit: AlerteProduit) => validerPrix(produit.anomalie_ids, produit.ligne_id),
    onSuccess: () => apresAction("Grille mise à jour."),
  });

  const contesterMutation = useMutation({
    mutationFn: (vars: { produit: AlerteProduit; commentaire: string }) =>
      contesterPrix(vars.produit.anomalie_ids, vars.commentaire),
    onSuccess: () => apresAction("Contesté auprès du fournisseur."),
  });

  const ignorerMutation = useMutation({
    mutationFn: (vars: { produit: AlerteProduit; commentaire: string }) =>
      ignorerPrix(vars.produit.anomalie_ids, vars.commentaire),
    onSuccess: () => apresAction("Alerte ignorée."),
  });

  const recontrole = useMutation({
    mutationFn: recontrolerPrix,
    onSuccess: (resultat) =>
      apresAction(
        `${resultat.nb_bons} ${accorder(resultat.nb_bons, "bon recontrôlé", "bons recontrôlés")}, ` +
          `${resultat.nb_alertes_ouvertes} ${accorder(resultat.nb_alertes_ouvertes, "alerte ouverte", "alertes ouvertes")}.`,
      ),
  });

  /** État (en cours, erreur) d'une rangée, tiré directement des trois
   * mutations plutôt que d'un état local dupliqué : `variables` porte le
   * produit de la dernière tentative de chaque mutation, comparé à la clé
   * de la rangée (spec §8.3, « après action : la rangée disparaît, message
   * bref » -- une erreur ne doit s'afficher que sous la rangée et le
   * panneau qui l'ont provoquée, jamais après une rangée déjà retraitée). */
  function actionsPour(produit: AlerteProduit): ReactElement {
    const cle = cleProduit(produit);
    const panneauOuvert = panneau?.cle === cle ? panneau.type : null;

    const validerCetteLigne = validerMutation.variables !== undefined && cleProduit(validerMutation.variables) === cle;
    const contesterCetteLigne =
      contesterMutation.variables !== undefined && cleProduit(contesterMutation.variables.produit) === cle;
    const ignorerCetteLigne =
      ignorerMutation.variables !== undefined && cleProduit(ignorerMutation.variables.produit) === cle;

    const enCours =
      (validerCetteLigne && validerMutation.isPending) ||
      (contesterCetteLigne && contesterMutation.isPending) ||
      (ignorerCetteLigne && ignorerMutation.isPending);

    let erreur: string | null = null;
    if (panneauOuvert === null && validerCetteLigne && validerMutation.isError) {
      erreur = messageErreur(validerMutation.error, "Le prix n'a pas pu être validé.");
    } else if (panneauOuvert === "contester" && contesterCetteLigne && contesterMutation.isError) {
      erreur = messageErreur(contesterMutation.error, "L'alerte n'a pas pu être contestée.");
    } else if (panneauOuvert === "ignorer" && ignorerCetteLigne && ignorerMutation.isError) {
      erreur = messageErreur(ignorerMutation.error, "L'alerte n'a pas pu être ignorée.");
    }

    return (
      <ActionsAlertePrix
        produit={produit}
        panneauOuvert={panneauOuvert}
        commentaire={panneauOuvert !== null ? commentaire : ""}
        enCours={enCours}
        erreur={erreur}
        onOuvrirPanneau={(type) => {
          setPanneau({ cle, type });
          setCommentaire("");
        }}
        onFermerPanneau={() => {
          setPanneau(null);
          setCommentaire("");
        }}
        onCommentaireChange={setCommentaire}
        onValider={() => validerMutation.mutate(produit)}
        onConfirmerPanneau={() => {
          if (panneauOuvert === "contester") {
            contesterMutation.mutate({ produit, commentaire });
          } else if (panneauOuvert === "ignorer") {
            ignorerMutation.mutate({ produit, commentaire });
          }
        }}
      />
    );
  }

  const optionsPeriode: OptionFiltre[] = [
    { valeur: "tout", libelle: "Tout" },
    { valeur: "jour", libelle: "Aujourd'hui" },
  ];

  return (
    <div className="space-y-6">
      <EnTetePage
        surtitre={
          controleActif && alertes.data
            ? `${alertes.data.length} ${accorder(alertes.data.length, "produit en alerte", "produits en alerte")}`
            : undefined
        }
        titre="Prix à vérifier"
        actions={
          controleActif ? (
            <Bouton variante="secondaire" onClick={() => recontrole.mutate()} disabled={recontrole.isPending}>
              {recontrole.isPending ? "Recontrôle en cours…" : "Recontrôler les bons"}
            </Bouton>
          ) : undefined
        }
      />

      {message !== null && (
        <p role="status" className="text-sm text-conforme">
          {message}
        </p>
      )}

      {recontrole.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreur(recontrole.error, "Le recontrôle n'a pas pu être lancé.")}
        </p>
      )}

      {parametres.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}

      {parametres.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les réglages.
        </p>
      )}

      {!parametres.isPending && !parametres.isError && !controleActif && (
        <Carte>
          <p className="text-sm text-encre">
            Le contrôle des prix des bons est éteint. Il s'allume dans{" "}
            <Link to="/reglages" className="font-medium text-accent underline">
              Réglages
            </Link>
            .
          </p>
        </Carte>
      )}

      {controleActif && (
        <>
          <Carte>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <Filtres
                options={optionsPeriode}
                valeur={filtres.periode}
                onChange={(valeur) => setFiltres((f) => ({ ...f, periode: valeur as PeriodeAlertesPrix }))}
              />
              <div>
                <label htmlFor="prix-fournisseur" className="sr-only">
                  Fournisseur
                </label>
                <select
                  id="prix-fournisseur"
                  value={filtres.fournisseurId}
                  onChange={(e) => setFiltres((f) => ({ ...f, fournisseurId: e.target.value }))}
                  className={CLASSES_CHAMP}
                >
                  <option value="">Tous les fournisseurs</option>
                  {fournisseurs.data?.map((fournisseur) => (
                    <option key={fournisseur.id} value={fournisseur.id}>
                      {fournisseur.nom}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </Carte>

          {alertes.isPending && (
            <p role="status" className="text-sm text-encre-2">
              Chargement des alertes de prix…
            </p>
          )}
          {alertes.isError && (
            <p role="alert" className="text-sm text-alerte">
              Impossible de charger les alertes de prix.
            </p>
          )}
          {alertes.data && alertes.data.length === 0 && (
            <EtatVide message="Aucun produit en alerte pour l'instant." />
          )}

          {alertes.data && alertes.data.length > 0 && (
            <>
              {/* Cartes — téléphone (< md). */}
              <ul className="space-y-3 md:hidden">
                {alertes.data.map((produit) => (
                  <CarteAlertePrix
                    key={cleProduit(produit)}
                    produit={produit}
                    actions={actionsPour(produit)}
                    colonneInternetVisible={colonneInternetVisible}
                    prixInternet={prixInternetPour(produit)}
                  />
                ))}
              </ul>

              {/* Tableau — ordinateur (>= md), 6 colonnes au plus (spec
                  §8.3) : produit, prix du bon, grille, dernier prix
                  facturé, écart (avec la ressemblance), alertes/lien --
                  7ᵉ colonne « Internet » (T10b, phase 4 IA) seulement quand
                  l'IA est active (`colonneInternetVisible`), jamais montrée
                  sinon (page inchangée, IA éteinte). Rangées compactes : les
                  trois actions occupent une ligne pleine largeur sous les
                  informations du produit plutôt que la colonne Alertes (trop
                  étroite pour trois boutons côte à côte -- constat capture,
                  tour 2), qui garde une largeur raisonnable pour les titres
                  d'alertes et le lien « Voir le bon ». */}
              <div className="hidden overflow-x-auto rounded-carte border border-bordure md:block">
                <table className="w-full min-w-[960px] text-sm">
                  <caption className="sr-only">Produits en alerte de prix</caption>
                  <thead className="bg-fond text-left text-xs font-medium uppercase tracking-wide text-encre-2">
                    <tr>
                      <th scope="col" className="w-full px-5 py-3">Produit</th>
                      <th scope="col" className="px-5 py-3">Prix du bon</th>
                      <th scope="col" className="px-5 py-3">Grille</th>
                      <th scope="col" className="px-5 py-3">Dernier prix facturé</th>
                      {colonneInternetVisible && (
                        <th scope="col" className="px-5 py-3">Internet</th>
                      )}
                      <th scope="col" className="px-5 py-3">Écart</th>
                      <th scope="col" className="min-w-[14rem] px-5 py-3">Alertes</th>
                    </tr>
                  </thead>
                  <tbody className="bg-surface">
                    {alertes.data.map((produit) => {
                      const ressemblance = texteRessemblance(produit);
                      return (
                        <Fragment key={cleProduit(produit)}>
                          <tr className="border-t border-bordure">
                            <th scope="row" className="px-5 pb-1 pt-3 text-left align-top font-medium text-encre">
                              <p className="whitespace-normal break-words">{produit.produit}</p>
                              <p className="mt-0.5 text-xs font-normal text-encre-2">
                                {texteCodeFournisseur(produit)}
                              </p>
                            </th>
                            <td className="px-5 pb-1 pt-3 align-top text-encre">
                              <PrixBonAffiche produit={produit} />
                            </td>
                            <td className="px-5 pb-1 pt-3 align-top text-encre">{texteGrille(produit)}</td>
                            <td className="px-5 pb-1 pt-3 align-top text-encre">{texteDernierPrix(produit)}</td>
                            {colonneInternetVisible && (
                              <td className="px-5 pb-1 pt-3 align-top text-encre">
                                <PrixInternetCellule produit={produit} prixInternet={prixInternetPour(produit)} />
                              </td>
                            )}
                            <td className="px-5 pb-1 pt-3 align-top font-mono font-medium text-encre">
                              {texteEcart(produit) ?? TIRET}
                              {ressemblance !== null && (
                                <p className="mt-0.5 text-xs font-normal text-encre-2">{ressemblance}</p>
                              )}
                            </td>
                            <td className="min-w-[14rem] px-5 pb-1 pt-3 align-top text-encre">
                              <p>{texteAlertes(produit)}</p>
                              <Link
                                to={lienBon(produit.document_id)}
                                className="mt-1 inline-flex min-h-[44px] items-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
                              >
                                Voir le bon
                              </Link>
                            </td>
                          </tr>
                          <tr>
                            <td colSpan={colonneInternetVisible ? 7 : 6} className="px-5 pb-3 pt-0 align-top">
                              {actionsPour(produit)}
                            </td>
                          </tr>
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
