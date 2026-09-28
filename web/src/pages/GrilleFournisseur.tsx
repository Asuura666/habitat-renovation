import { type ChangeEvent, type FormEvent, type ReactElement, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router";

import {
  type ApercuImport,
  apercevoirImportGrille,
  cleGrilleFournisseur,
  type ProduitGrille,
  enregistrerPrixGrille,
  importerGrille,
  obtenirGrilleFournisseur,
  type SaisiePrixGrille,
  retirerProduitGrille,
  urlModeleGrille,
} from "../api/grilles";
import { ErreurApi } from "../api/client";
import { CLE_FOURNISSEURS, listerFournisseurs } from "../api/referentiels";
import { formaterDate, formaterMontant, formaterDateHeure, TIRET } from "../lib/formats";
import { Bouton, Carte, EnTetePage, EtatVide, FilAriane } from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";

const CLASSES_ETIQUETTE = "mb-1 block text-sm font-medium text-encre";

const FORMATEUR_AUJOURDHUI = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** « Aujourd'hui » en heure de Paris (`AAAA-MM-JJ`), jamais en UTC -- même
 * technique que `moisCourant()` (`VueEnsemble.tsx`) : entre minuit UTC et
 * minuit heure de Paris, `new Date().toISOString()` renvoie encore la
 * veille (constat de relecture qualité, tour 2). Sert de valeur par défaut
 * aux formulaires (champ modifiable) et de date d'effet du retrait, qui
 * n'affiche aucun champ de date à corriger. */
function aujourdhuiIso(): string {
  const parties = FORMATEUR_AUJOURDHUI.formatToParts(new Date());
  const annee = parties.find((partie) => partie.type === "year")?.value ?? "0000";
  const mois = parties.find((partie) => partie.type === "month")?.value ?? "01";
  const jour = parties.find((partie) => partie.type === "day")?.value ?? "01";
  return `${annee}-${mois}-${jour}`;
}

function messageErreur(erreur: unknown, repli: string): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return repli;
}

/** Formulaire de saisie d'un produit (spec §9 : « Modifier » sur une
 * rangée ouvre un petit formulaire limité au prix, à la remise, à l'unité
 * et à la date d'effet ; « Ajouter un produit » ouvre le formulaire complet,
 * avec désignation, référence, marque et famille). La désignation et la
 * référence déterminent la clé du produit côté serveur
 * (`cle_produit(reference, designation)`, `ingest/grilles.py`) : les rendre
 * modifiables en édition créerait, pour une simple correction de faute de
 * frappe, un produit distinct dans la grille au lieu de mettre à jour celui
 * visé -- elles restent donc en lecture seule quand `produit` est fourni. */
function FormulaireProduit({
  produit,
  onAnnuler,
  onEnregistre,
}: {
  produit: ProduitGrille | null;
  onAnnuler: () => void;
  onEnregistre: () => void;
}): ReactElement {
  const { fournisseurId } = useParams();
  const enModification = produit !== null;
  const [reference, setReference] = useState(produit?.reference ?? "");
  const [designation, setDesignation] = useState(produit?.designation ?? "");
  const [unite, setUnite] = useState(produit?.unite_brut ?? "");
  const [prixHt, setPrixHt] = useState(produit ? String(produit.prix_ht) : "");
  const [remise, setRemise] = useState(produit?.remise_pct ? String(produit.remise_pct) : "");
  const [dateEffet, setDateEffet] = useState(aujourdhuiIso());
  const [marque, setMarque] = useState(produit?.marque ?? "");
  const [famille, setFamille] = useState(produit?.famille ?? "");

  const enregistrement = useMutation({
    mutationFn: () => {
      const saisie: SaisiePrixGrille = {
        reference: reference.trim() || null,
        designation: designation.trim(),
        unite: unite.trim() || null,
        prix_ht: prixHt,
        remise_pct: remise.trim() || null,
        date_effet: dateEffet || null,
        marque: marque.trim() || null,
        famille: famille.trim() || null,
      };
      return enregistrerPrixGrille(fournisseurId ?? "", saisie);
    },
    onSuccess: onEnregistre,
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    enregistrement.mutate();
  }

  return (
    <form onSubmit={soumettre} className="grid gap-3 rounded-carte border border-bordure bg-fond p-4 sm:grid-cols-2">
      {!enModification && (
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="produit-designation">
            Désignation
          </label>
          <input
            id="produit-designation"
            value={designation}
            onChange={(e) => setDesignation(e.target.value)}
            required
            className={CLASSES_CHAMP}
          />
        </div>
      )}
      {!enModification && (
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="produit-reference">
            Référence (facultative)
          </label>
          <input
            id="produit-reference"
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
      )}
      {enModification && (
        <div className="sm:col-span-2">
          <p className={CLASSES_ETIQUETTE}>Produit</p>
          <p className="text-sm text-encre">
            {designation}
            {reference ? ` (${reference})` : ""}
          </p>
        </div>
      )}
      <div>
        <label className={CLASSES_ETIQUETTE} htmlFor="produit-prix">
          Prix unitaire HT
        </label>
        <input
          id="produit-prix"
          type="number"
          step="any"
          inputMode="decimal"
          value={prixHt}
          onChange={(e) => setPrixHt(e.target.value)}
          required
          className={CLASSES_CHAMP}
        />
      </div>
      <div>
        <label className={CLASSES_ETIQUETTE} htmlFor="produit-remise">
          Remise % (facultative)
        </label>
        <input
          id="produit-remise"
          type="number"
          step="any"
          inputMode="decimal"
          value={remise}
          onChange={(e) => setRemise(e.target.value)}
          className={CLASSES_CHAMP}
        />
      </div>
      <div>
        <label className={CLASSES_ETIQUETTE} htmlFor="produit-unite">
          Unité (facultative)
        </label>
        <input
          id="produit-unite"
          value={unite}
          onChange={(e) => setUnite(e.target.value)}
          className={CLASSES_CHAMP}
        />
      </div>
      <div>
        <label className={CLASSES_ETIQUETTE} htmlFor="produit-date-effet">
          Date d'effet
        </label>
        <input
          id="produit-date-effet"
          type="date"
          value={dateEffet}
          onChange={(e) => setDateEffet(e.target.value)}
          required
          className={CLASSES_CHAMP}
        />
      </div>
      {!enModification && (
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="produit-marque">
            Marque (facultative)
          </label>
          <input
            id="produit-marque"
            value={marque}
            onChange={(e) => setMarque(e.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
      )}
      {!enModification && (
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="produit-famille">
            Famille (facultative)
          </label>
          <input
            id="produit-famille"
            value={famille}
            onChange={(e) => setFamille(e.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
      )}

      {enregistrement.isError && (
        <p role="alert" className="sm:col-span-2 text-sm text-alerte">
          {messageErreur(enregistrement.error, "Le prix n'a pas pu être enregistré.")}
        </p>
      )}

      <div className="flex gap-2 sm:col-span-2">
        <Bouton type="submit" disabled={enregistrement.isPending}>
          {enregistrement.isPending ? "Enregistrement…" : "Enregistrer"}
        </Bouton>
        <Bouton type="button" variante="secondaire" onClick={onAnnuler}>
          Annuler
        </Bouton>
      </div>
    </form>
  );
}

/** Une rangée de la grille, en carte (téléphone) — mêmes informations que
 * le tableau ci-dessous (spec §9). */
function CarteProduit({
  produit,
  surModifier,
  surRetirer,
  retraitEnCours,
}: {
  produit: ProduitGrille;
  surModifier: () => void;
  surRetirer: () => void;
  retraitEnCours: boolean;
}): ReactElement {
  return (
    <li className="rounded-carte border border-bordure bg-surface p-4">
      <p className="font-medium text-encre">{produit.designation}</p>
      <p className="text-sm text-encre-2">{produit.reference ?? "Sans référence"}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Prix net</dt>
          <dd className="font-mono font-medium text-encre">
            {formaterMontant(produit.prix_net)}
            {produit.remise_pct !== null && (
              <span className="ml-1 text-xs text-encre-2">
                ({formaterMontant(produit.prix_ht)} − {produit.remise_pct} %)
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Unité</dt>
          <dd className="text-encre">{produit.unite_brut ?? TIRET}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Date d'effet</dt>
          <dd className="text-encre">{formaterDate(produit.date_effet)}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Famille</dt>
          <dd className="text-encre">{produit.famille ?? TIRET}</dd>
        </div>
      </dl>
      <div className="mt-3 flex gap-2">
        <Bouton variante="secondaire" onClick={surModifier} disabled={retraitEnCours}>
          Modifier
        </Bouton>
        <Bouton variante="secondaire" onClick={surRetirer} disabled={retraitEnCours}>
          {retraitEnCours ? "Retrait…" : "Retirer de la grille"}
        </Bouton>
      </div>
    </li>
  );
}

function ligneComparee(designation: string, reference: string | null, ancien: string | null, nouveau: string): string {
  const nom = reference ? `${designation} (${reference})` : designation;
  return ancien !== null ? `${nom} : ${formaterMontant(ancien)} → ${formaterMontant(nouveau)}` : nom;
}

/** Aperçu de l'import (spec §9) : compteurs, 50 premiers nouveaux/modifiés,
 * erreurs ligne par ligne, produits absents du fichier (repliés) -- aucune
 * écriture tant que « Importer » n'est pas cliqué. */
function SectionApercu({
  apercu,
  surConfirmer,
  surAnnuler,
  enCours,
}: {
  apercu: ApercuImport;
  surConfirmer: () => void;
  surAnnuler: () => void;
  enCours: boolean;
}): ReactElement {
  const [absentsOuverts, setAbsentsOuverts] = useState(false);
  const nbAImporter = apercu.nb_nouveaux + apercu.nb_modifies;
  const mentionErreurs =
    apercu.nb_erreurs > 0
      ? ` — ${apercu.nb_erreurs} ligne${apercu.nb_erreurs > 1 ? "s" : ""} en erreur seront ignorée${apercu.nb_erreurs > 1 ? "s" : ""}`
      : "";

  return (
    <div className="mt-4 space-y-4 rounded-carte border border-bordure bg-fond p-4">
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          <strong className="text-encre">{apercu.nb_nouveaux}</strong> nouveaux
        </span>
        <span>
          <strong className="text-encre">{apercu.nb_modifies}</strong> modifiés
        </span>
        <span>
          <strong className="text-encre">{apercu.nb_inchanges}</strong> inchangés
        </span>
        <span className={apercu.nb_erreurs > 0 ? "text-alerte" : undefined}>
          <strong>{apercu.nb_erreurs}</strong> en erreur
        </span>
      </div>

      {apercu.nouveaux.length > 0 && (
        <div>
          <h3 className="mb-2 font-medium text-encre">Nouveaux produits</h3>
          <ul className="space-y-1 text-sm text-encre">
            {apercu.nouveaux.slice(0, 50).map((ligne, index) => (
              <li key={`nouveau-${index}`}>
                {ligneComparee(ligne.designation, ligne.reference, null, ligne.nouveau_prix_net)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {apercu.modifies.length > 0 && (
        <div>
          <h3 className="mb-2 font-medium text-encre">Produits modifiés</h3>
          <ul className="space-y-1 text-sm text-encre">
            {apercu.modifies.slice(0, 50).map((ligne, index) => (
              <li key={`modifie-${index}`}>
                {ligneComparee(
                  ligne.designation,
                  ligne.reference,
                  ligne.ancien_prix_net,
                  ligne.nouveau_prix_net,
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {apercu.erreurs.length > 0 && (
        <div>
          <h3 className="mb-2 font-medium text-alerte">Lignes en erreur</h3>
          <ul className="space-y-1 text-sm text-encre">
            {apercu.erreurs.map((erreur, index) => (
              <li key={`erreur-${index}`}>
                {erreur.feuille}, ligne {erreur.numero_ligne} : {erreur.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {apercu.absents_du_fichier.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setAbsentsOuverts((v) => !v)}
            className="min-h-[44px] text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          >
            {absentsOuverts ? "Masquer" : "Voir"} les {apercu.absents_du_fichier.length} produits absents
            de ce fichier
          </button>
          {absentsOuverts && (
            <ul className="mt-2 space-y-1 text-sm text-encre-2">
              {apercu.absents_du_fichier.map((produit, index) => (
                <li key={`absent-${index}`}>
                  {ligneComparee(produit.designation, produit.reference, null, produit.prix_net)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Bouton onClick={surConfirmer} disabled={enCours || nbAImporter === 0}>
          {enCours ? "Import en cours…" : `Importer ${nbAImporter} prix${mentionErreurs}`}
        </Bouton>
        <Bouton variante="secondaire" onClick={surAnnuler} disabled={enCours}>
          Annuler
        </Bouton>
      </div>
    </div>
  );
}

/** Section « Importer un fichier » (spec §9) : modèle, choix du fichier et
 * de la date d'effet, aperçu puis confirmation. */
function SectionImport({ onImporte }: { onImporte: (resume: string) => void }): ReactElement {
  const { fournisseurId } = useParams();
  const entreeFichier = useRef<HTMLInputElement>(null);
  const [fichier, setFichier] = useState<File | null>(null);
  const [dateEffet, setDateEffet] = useState(aujourdhuiIso());
  const [apercu, setApercu] = useState<ApercuImport | null>(null);

  const previsualisation = useMutation({
    mutationFn: () => apercevoirImportGrille(fournisseurId ?? "", fichier as File, dateEffet),
    onSuccess: setApercu,
  });

  const confirmation = useMutation({
    mutationFn: () => importerGrille(fournisseurId ?? "", fichier as File, dateEffet),
    onSuccess: (resultat) => {
      setApercu(null);
      setFichier(null);
      if (entreeFichier.current) {
        entreeFichier.current.value = "";
      }
      onImporte(
        `Import terminé : ${resultat.nb_nouveaux} nouveaux, ${resultat.nb_modifies} modifiés, ${resultat.nb_erreurs} en erreur.`,
      );
    },
  });

  function choisirFichier(evenement: ChangeEvent<HTMLInputElement>): void {
    setApercu(null);
    setFichier(evenement.target.files?.[0] ?? null);
  }

  return (
    <Carte titre="Importer un fichier">
      <div className="flex flex-wrap items-end gap-3">
        <a href={urlModeleGrille()} download className="min-h-[44px] inline-flex items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
          Télécharger le modèle
        </a>
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="import-fichier">
            Fichier
          </label>
          <input
            id="import-fichier"
            ref={entreeFichier}
            type="file"
            accept=".xlsx"
            onChange={choisirFichier}
            className="text-sm text-encre"
          />
        </div>
        <div>
          <label className={CLASSES_ETIQUETTE} htmlFor="import-date-effet">
            Date d'effet
          </label>
          <input
            id="import-date-effet"
            type="date"
            value={dateEffet}
            onChange={(e) => {
              // Un aperçu déjà affiché a été calculé pour l'ancienne date :
              // il faut le refaire avant toute confirmation (spec §9,
              // « aperçu avant import »), comme au changement de fichier.
              setApercu(null);
              setDateEffet(e.target.value);
            }}
            className={CLASSES_CHAMP}
          />
        </div>
        <Bouton
          onClick={() => previsualisation.mutate()}
          disabled={fichier === null || previsualisation.isPending}
        >
          {previsualisation.isPending ? "Analyse…" : "Voir l'aperçu"}
        </Bouton>
      </div>

      {previsualisation.isError && (
        <p role="alert" className="mt-2 text-sm text-alerte">
          {messageErreur(previsualisation.error, "Ce fichier n'a pas pu être analysé.")}
        </p>
      )}
      {confirmation.isError && (
        <p role="alert" className="mt-2 text-sm text-alerte">
          {messageErreur(confirmation.error, "L'import n'a pas pu être confirmé.")}
        </p>
      )}

      {apercu !== null && (
        <SectionApercu
          apercu={apercu}
          enCours={confirmation.isPending}
          surConfirmer={() => confirmation.mutate()}
          surAnnuler={() => setApercu(null)}
        />
      )}
    </Carte>
  );
}

/**
 * Grille de prix d'un fournisseur (`/fournisseurs/:fournisseurId/prix`,
 * phase 3, tâche P5, spec §9) : prix en vigueur aujourd'hui, recherche,
 * saisie/retrait manuels, import Excel avec aperçu. Admin seulement
 * (`GardeAdmin`, `App.tsx`) — les routes de l'API sont de toute façon
 * réservées à l'admin (`admin_requis`, `api/grilles.py`).
 */
export function GrilleFournisseur(): ReactElement {
  const { fournisseurId } = useParams();
  const queryClient = useQueryClient();
  const [recherche, setRecherche] = useState("");
  const [page, setPage] = useState(1);
  const [ajoutOuvert, setAjoutOuvert] = useState(false);
  // Formulaire de modification affiché au-dessus de la liste (jamais imbriqué
  // dans une ligne de tableau : un `<td colSpan>` contenant une grille à deux
  // colonnes casse le calcul des largeurs de colonnes du tableau, constat de
  // la vérification visuelle de la tâche P5 -- même emplacement que le
  // formulaire d'ajout, au-dessus de la liste, sur téléphone comme sur
  // ordinateur). `null` : aucune modification en cours.
  const [produitEnEdition, setProduitEnEdition] = useState<ProduitGrille | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });
  const grille = useQuery({
    queryKey: cleGrilleFournisseur(fournisseurId ?? "", recherche, page),
    queryFn: () => obtenirGrilleFournisseur(fournisseurId ?? "", { recherche, page }),
    enabled: fournisseurId !== undefined,
  });

  // Clé du produit en cours de retrait (`null` : aucun) -- sert à ne
  // désactiver que le bouton de sa ligne pendant la requête (constat de
  // relecture qualité, tour 2), comme les autres actions de l'écran
  // désactivent déjà leur propre bouton.
  const [cleEnRetrait, setCleEnRetrait] = useState<string | null>(null);

  const retrait = useMutation({
    mutationFn: (produit: ProduitGrille) =>
      retirerProduitGrille(fournisseurId ?? "", produit.cle_produit, aujourdhuiIso()),
    onSuccess: async () => {
      setMessage("Produit retiré de la grille.");
      await queryClient.invalidateQueries({ queryKey: ["grille", fournisseurId ?? ""] });
    },
    onSettled: () => setCleEnRetrait(null),
  });

  async function rafraichir(): Promise<void> {
    await queryClient.invalidateQueries({ queryKey: ["grille", fournisseurId ?? ""] });
  }

  const nom = fournisseurs.data?.find((f) => f.id === fournisseurId)?.nom ?? "Fournisseur";

  function surRetirer(produit: ProduitGrille): void {
    if (window.confirm(`Retirer « ${produit.designation} » de la grille ?`)) {
      setCleEnRetrait(produit.cle_produit);
      retrait.mutate(produit);
    }
  }

  return (
    <div className="space-y-6">
      <FilAriane
        elements={[
          { libelle: "Fournisseurs", vers: "/fournisseurs" },
          { libelle: nom, vers: `/fournisseurs/${fournisseurId ?? ""}` },
          { libelle: "Grille de prix" },
        ]}
      />

      <EnTetePage
        surtitre={
          grille.data
            ? `${grille.data.nb_produits} produit${grille.data.nb_produits > 1 ? "s" : ""} · dernier import ${
                grille.data.dernier_import_le ? formaterDateHeure(grille.data.dernier_import_le) : "jamais"
              }`
            : undefined
        }
        titre={`Grille de prix — ${nom}`}
        actions={
          <Bouton onClick={() => setAjoutOuvert((v) => !v)}>
            {ajoutOuvert ? "Fermer" : "Ajouter un produit"}
          </Bouton>
        }
      />

      {message !== null && (
        <p role="status" className="text-sm text-conforme">
          {message}
        </p>
      )}

      {retrait.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreur(retrait.error, "Le produit n'a pas pu être retiré de la grille.")}
        </p>
      )}

      {ajoutOuvert && (
        <FormulaireProduit
          produit={null}
          onAnnuler={() => setAjoutOuvert(false)}
          onEnregistre={() => {
            setAjoutOuvert(false);
            setMessage("Produit ajouté à la grille.");
            void rafraichir();
          }}
        />
      )}

      {produitEnEdition !== null && (
        <FormulaireProduit
          produit={produitEnEdition}
          onAnnuler={() => setProduitEnEdition(null)}
          onEnregistre={() => {
            setProduitEnEdition(null);
            setMessage("Prix mis à jour.");
            void rafraichir();
          }}
        />
      )}

      <Carte>
        <label className="sr-only" htmlFor="recherche-grille">
          Rechercher un produit
        </label>
        <input
          id="recherche-grille"
          type="search"
          placeholder="Rechercher par référence ou désignation…"
          value={recherche}
          onChange={(e) => {
            setPage(1);
            setRecherche(e.target.value);
          }}
          className={CLASSES_CHAMP}
        />

        {grille.isPending && (
          <p role="status" className="mt-4 text-sm text-encre-2">
            Chargement de la grille…
          </p>
        )}
        {grille.isError && (
          <p role="alert" className="mt-4 text-sm text-alerte">
            Impossible de charger la grille de ce fournisseur.
          </p>
        )}
        {grille.data && grille.data.produits.length === 0 && (
          <div className="mt-4">
            <EtatVide message="Aucun produit dans cette grille pour l'instant." />
          </div>
        )}

        {grille.data && grille.data.produits.length > 0 && (
          <>
            {/* Cartes — téléphone (< md). */}
            <ul className="mt-4 space-y-3 md:hidden">
              {grille.data.produits.map((produit) => (
                <CarteProduit
                  key={produit.cle_produit}
                  produit={produit}
                  surModifier={() => setProduitEnEdition(produit)}
                  surRetirer={() => surRetirer(produit)}
                  retraitEnCours={cleEnRetrait === produit.cle_produit}
                />
              ))}
            </ul>

            {/* Tableau — ordinateur (>= md). */}
            <div className="mt-4 hidden overflow-x-auto rounded-carte border border-bordure md:block">
              <table className="w-full min-w-[720px] divide-y divide-bordure text-sm">
                <caption className="sr-only">Prix en vigueur de la grille</caption>
                <thead className="bg-fond text-left text-xs font-medium uppercase tracking-wide text-encre-2">
                  <tr>
                    <th scope="col" className="px-5 py-3">Désignation</th>
                    <th scope="col" className="px-5 py-3">Référence</th>
                    <th scope="col" className="px-5 py-3">Unité</th>
                    <th scope="col" className="px-5 py-3 text-right">Prix net</th>
                    <th scope="col" className="px-5 py-3">Date d'effet</th>
                    <th scope="col" className="px-5 py-3">Famille</th>
                    <th scope="col" className="px-5 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-bordure bg-surface">
                  {grille.data.produits.map((produit) => (
                    <tr key={produit.cle_produit}>
                      <th scope="row" className="px-5 py-3 text-left font-medium text-encre">
                        {produit.designation}
                      </th>
                      <td className="px-5 py-3 text-encre">{produit.reference ?? TIRET}</td>
                      <td className="px-5 py-3 text-encre">{produit.unite_brut ?? TIRET}</td>
                      <td className="px-5 py-3 text-right font-mono text-encre">
                        {formaterMontant(produit.prix_net)}
                        {produit.remise_pct !== null && (
                          <span className="ml-1 text-xs text-encre-2">
                            ({formaterMontant(produit.prix_ht)} − {produit.remise_pct} %)
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-encre">{formaterDate(produit.date_effet)}</td>
                      <td className="px-5 py-3 text-encre">{produit.famille ?? TIRET}</td>
                      <td className="px-5 py-3 text-right">
                        <div className="flex justify-end gap-2">
                          <Bouton
                            variante="secondaire"
                            onClick={() => setProduitEnEdition(produit)}
                            disabled={cleEnRetrait === produit.cle_produit}
                          >
                            Modifier
                          </Bouton>
                          <Bouton
                            variante="secondaire"
                            onClick={() => surRetirer(produit)}
                            disabled={cleEnRetrait === produit.cle_produit}
                          >
                            {cleEnRetrait === produit.cle_produit ? "Retrait…" : "Retirer"}
                          </Bouton>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {grille.data.pages > 1 && (
              <div className="mt-4 flex items-center justify-between text-sm text-encre-2">
                <Bouton
                  variante="secondaire"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Page précédente
                </Bouton>
                <span>
                  Page {grille.data.page} sur {grille.data.pages}
                </span>
                <Bouton
                  variante="secondaire"
                  disabled={page >= grille.data.pages}
                  onClick={() => setPage((p) => Math.min(grille.data?.pages ?? p, p + 1))}
                >
                  Page suivante
                </Bouton>
              </div>
            )}
          </>
        )}
      </Carte>

      <SectionImport
        onImporte={(resume) => {
          setMessage(resume);
          void rafraichir();
        }}
      />
    </div>
  );
}
