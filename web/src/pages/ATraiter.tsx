import { type FormEvent, type ReactElement, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  CLE_A_TRAITER,
  type AliasEnAttente,
  type ArticleAValider,
  type DocumentATraiter,
  obtenirATraiter,
} from "../api/aTraiter";
import type { Anomalie } from "../api/anomalies";
import { ErreurApi } from "../api/client";
import {
  CLE_CHANTIERS,
  type Chantier,
  ChantierEnDoubleErreur,
  creerChantier,
  listerChantiers,
  validerAlias,
  validerArticle,
} from "../api/referentiels";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";
import { justification, libelleRegle } from "../lib/regles";

/** `type` d'un document « à vérifier » (BL, enlèvement ou facture, L3-D18) :
 * présentation uniquement, décision du contrôleur — même principe que
 * `libelleType` de `BlDeposes.tsx`, complété ici de « facture » et « avoir »
 * (`document.type` du modèle, `app/modules/ingest/models.py`). */
function libelleTypeDocument(type: string): string {
  switch (type) {
    case "bl":
      return "Livraison";
    case "enlevement":
      return "Enlèvement";
    case "facture":
      return "Facture";
    case "avoir":
      return "Avoir";
    default:
      return type;
  }
}

/** Une facture « à vérifier » renvoie vers `/factures/:id`, un BL ou un
 * enlèvement vers `/documents/:id` (L3-D19). `/documents/:id` n'existe pas
 * encore (route créée par L3-T10, Ruling R2) : le routeur ramène l'admin à
 * l'accueil tant que la route est absente — aucune page provisoire créée
 * ici. */
function cheminDocument(document: DocumentATraiter): string {
  return document.type === "facture" ? `/factures/${document.id}` : `/documents/${document.id}`;
}

/** Même logique que `cheminDocument` ci-dessus, appliquée à une anomalie
 * (`document_id`/`type` d'`AnomalieReponse`) : `null` si l'anomalie n'a pas
 * de document rattaché (R14 — alias, R16 — chantier, décision du
 * contrôleur, jamais le cas ici car la section ne montre que des anomalies
 * de gravité haute, mais la garde reste défensive). */
function cheminDocumentAnomalie(anomalie: Anomalie): string | null {
  if (anomalie.document_id === null) {
    return null;
  }
  return anomalie.type === "facture" ? `/factures/${anomalie.document_id}` : `/documents/${anomalie.document_id}`;
}

function BadgeHaute(): ReactElement {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
      Haute
    </span>
  );
}

/** Carte compacte d'une anomalie « ouverte de gravité haute » (L4-D18) :
 * règle, justification chiffrée et lien vers le document source — jamais
 * les actions « Traitée »/« Ignorée » (elles vivent sur l'écran complet,
 * `pages/Anomalies.tsx`, vers lequel cette section renvoie). */
function AnomalieHauteCarte({ anomalie }: { anomalie: Anomalie }): ReactElement {
  const chemin = cheminDocumentAnomalie(anomalie);
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold text-slate-900">{libelleRegle(anomalie.regle)}</p>
        <BadgeHaute />
      </div>
      <p className="mb-2 text-sm text-slate-700">{justification(anomalie)}</p>
      {chemin !== null && (
        <Link
          to={chemin}
          className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          {anomalie.type === "facture" ? "Voir la facture" : "Voir le document"}
        </Link>
      )}
    </li>
  );
}

function SectionAnomaliesHautes({ anomalies }: { anomalies: Anomalie[] }): ReactElement {
  if (anomalies.length === 0) {
    return <p className="text-sm text-slate-600">Rien à traiter.</p>;
  }
  return (
    <ul className="space-y-3">
      {anomalies.map((anomalie) => (
        <AnomalieHauteCarte key={anomalie.id} anomalie={anomalie} />
      ))}
    </ul>
  );
}

function BadgeEcart(): ReactElement {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
      Écart constaté
    </span>
  );
}

function MotifsListe({ document }: { document: DocumentATraiter }): ReactElement | null {
  if (document.motifs.length === 0) {
    return null;
  }
  return (
    <ul className="list-disc space-y-0.5 pl-5 text-sm text-slate-700">
      {document.motifs.map((motif, index) => (
        // Aucun identifiant stable côté API pour un motif : l'ordre de la
        // liste ne change qu'à un nouveau chargement (décision du
        // contrôleur, même situation que `FactureDetail.tsx::BlocCarte`).
        <li key={index}>{libelleMotif(motif)}</li>
      ))}
    </ul>
  );
}

function DocumentCarte({ document }: { document: DocumentATraiter }): ReactElement {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            Document n° {document.numero_interne} · {libelleTypeDocument(document.type)}
          </p>
          <p className="text-xs text-slate-500">
            {document.numero ?? "sans numéro"} · {document.fournisseur ?? TIRET} ·{" "}
            {formaterDateHeure(document.cree_le)}
          </p>
          <p className="text-xs text-slate-500">
            Chantier : {document.chantier_brut ?? TIRET} · Déposé par{" "}
            {document.deposant ?? TIRET}
          </p>
        </div>
        {document.confirmation === "ecart" && <BadgeEcart />}
      </div>

      <div className="mb-3">
        <MotifsListe document={document} />
      </div>

      <Link
        to={cheminDocument(document)}
        className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
      >
        {document.type === "facture" ? "Voir la facture" : "Voir le document"}
      </Link>
    </li>
  );
}

function DocumentLigne({ document }: { document: DocumentATraiter }): ReactElement {
  return (
    <tr>
      <td className="px-4 py-3 text-slate-700">{document.numero_interne}</td>
      <td className="px-4 py-3 text-slate-700">{libelleTypeDocument(document.type)}</td>
      <td className="px-4 py-3 text-slate-700">{document.numero ?? "sans numéro"}</td>
      <td className="px-4 py-3 text-slate-700">{document.fournisseur ?? TIRET}</td>
      <td className="px-4 py-3 text-slate-700">{document.chantier_brut ?? TIRET}</td>
      <td className="px-4 py-3 text-slate-700">{document.deposant ?? TIRET}</td>
      <td className="px-4 py-3 text-slate-700">{formaterDateHeure(document.cree_le)}</td>
      <td className="px-4 py-3">
        <div className="mb-1">
          <MotifsListe document={document} />
        </div>
        {document.confirmation === "ecart" && <BadgeEcart />}
      </td>
      <td className="px-4 py-3">
        <Link
          to={cheminDocument(document)}
          className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          {document.type === "facture" ? "Voir la facture" : "Voir le document"}
        </Link>
      </td>
    </tr>
  );
}

function SectionDocuments({ documents }: { documents: DocumentATraiter[] }): ReactElement {
  if (documents.length === 0) {
    return <p className="text-sm text-slate-600">Rien à traiter.</p>;
  }
  return (
    <>
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {documents.map((document) => (
          <DocumentCarte key={document.id} document={document} />
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block">
        <table className="w-full min-w-[1000px] divide-y divide-slate-200 text-sm">
          <caption className="sr-only">Documents à vérifier</caption>
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-4 py-3">N° interne</th>
              <th scope="col" className="px-4 py-3">Type</th>
              <th scope="col" className="px-4 py-3">Numéro</th>
              <th scope="col" className="px-4 py-3">Fournisseur</th>
              <th scope="col" className="px-4 py-3">Chantier (brut)</th>
              <th scope="col" className="px-4 py-3">Déposant</th>
              <th scope="col" className="px-4 py-3">Date</th>
              <th scope="col" className="px-4 py-3">Motifs</th>
              <th scope="col" className="px-4 py-3">
                <span className="sr-only">Lien</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {documents.map((document) => (
              <DocumentLigne key={document.id} document={document} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Levée par la mutation d'`AliasCarte` (fix round 1, revue L3-T9) quand
 * `creerChantier` a réussi mais que `validerAlias` échoue ensuite : le
 * chantier existe déjà en base, ce n'est pas une erreur de création (jamais
 * un `ChantierEnDoubleErreur`) mais un échec **partiel** qu'il faut nommer
 * distinctement — sinon un réessai recréerait le même chantier et
 * échouerait sur un 409 « existe déjà » sans issue depuis l'écran. */
class RattachementApresCreationErreur extends Error {
  constructor(cause: unknown) {
    super("chantier créé, rattachement de l'alias échoué", { cause });
    this.name = "RattachementApresCreationErreur";
  }
}

/** Formulaire de rattachement d'un alias chantier en attente (L3-D7) : un
 * sélecteur « Chantier existant » ou la création d'un chantier (nom,
 * agence) puis validation de l'alias avec l'id renvoyé, en une action
 * (décision du contrôleur). */
function AliasCarte({
  alias,
  chantiers,
}: {
  alias: AliasEnAttente;
  chantiers: Chantier[];
}): ReactElement {
  const queryClient = useQueryClient();
  const [modeCreation, setModeCreation] = useState(false);
  const [chantierChoisi, setChantierChoisi] = useState("");
  const [nom, setNom] = useState("");
  const [agence, setAgence] = useState("");
  // Id du chantier créé par un essai précédent de cette même carte, quand
  // `validerAlias` a ensuite échoué (fix round 1) : un réessai réutilise cet
  // id au lieu d'appeler `creerChantier` une seconde fois (qui échouerait,
  // le nom existant déjà). Remis à `null` dès qu'un rattachement réussit.
  const chantierCreeIdRef = useRef<string | null>(null);

  const validation = useMutation({
    mutationFn: async () => {
      let chantierId: string;
      if (modeCreation) {
        if (chantierCreeIdRef.current !== null) {
          chantierId = chantierCreeIdRef.current;
        } else {
          const cree = await creerChantier(nom, agence.trim() === "" ? null : agence.trim());
          chantierCreeIdRef.current = cree.id;
          chantierId = cree.id;
        }
      } else {
        chantierId = chantierChoisi;
      }

      try {
        const resultat = await validerAlias(alias.id, chantierId);
        chantierCreeIdRef.current = null;
        return resultat;
      } catch (erreur) {
        // `chantierId` existe déjà en base à ce stade (créé à cet essai ou
        // à un essai précédent) : le signaler distinctement de l'erreur
        // brute de `validerAlias` (fix round 1).
        if (modeCreation) {
          throw new RattachementApresCreationErreur(erreur);
        }
        throw erreur;
      }
    },
    // Que la validation réussisse ou échoue après une création de chantier,
    // le référentiel a pu changer (chantier créé) : jamais servir une liste
    // de chantiers périmée depuis le cache (`staleTime` global 5 min,
    // `main.tsx`) — fix round 1, invalide dans tous les cas via `onSettled`
    // plutôt que seulement `onSuccess`.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER });
      setModeCreation(false);
      setChantierChoisi("");
      setNom("");
      setAgence("");
    },
  });

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof RattachementApresCreationErreur) {
      return "Le chantier a été créé, son rattachement a échoué : réessayez.";
    }
    if (erreur instanceof ChantierEnDoubleErreur) {
      const existant = chantiers.find((chantier) => chantier.id === erreur.originalId);
      return existant
        ? `Le chantier « ${existant.nom_canonique} » existe déjà.`
        : "Ce chantier existe déjà.";
    }
    if (erreur instanceof ErreurApi) {
      return erreur.detail;
    }
    return "Une erreur est survenue, réessayez.";
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    validation.mutate();
  }

  const soumissionValide = modeCreation ? nom.trim() !== "" : chantierChoisi !== "";

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3">
        <p className="text-sm font-semibold text-slate-900">{alias.libelle}</p>
        <p className="text-xs text-slate-500">
          {alias.fournisseur} · {alias.nb_documents}{" "}
          {alias.nb_documents > 1 ? "documents" : "document"}
        </p>
        {alias.exemple_brut !== null && (
          <p className="text-xs text-slate-500">Exemple : {alias.exemple_brut}</p>
        )}
      </div>

      <form onSubmit={soumettre} className="space-y-3">
        {!modeCreation && (
          <div>
            <label
              htmlFor={`chantier-${alias.id}`}
              className="mb-1 block text-xs font-medium text-slate-700"
            >
              Chantier existant
            </label>
            <select
              id={`chantier-${alias.id}`}
              value={chantierChoisi}
              onChange={(evenement) => setChantierChoisi(evenement.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600 sm:w-auto"
            >
              <option value="">— Choisir —</option>
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
          <div className="grid grid-cols-1 gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor={`nom-${alias.id}`}
                className="mb-1 block text-xs font-medium text-slate-700"
              >
                Nom du chantier
              </label>
              <input
                id={`nom-${alias.id}`}
                type="text"
                value={nom}
                onChange={(evenement) => setNom(evenement.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              />
            </div>
            <div>
              <label
                htmlFor={`agence-${alias.id}`}
                className="mb-1 block text-xs font-medium text-slate-700"
              >
                Agence
              </label>
              <input
                id={`agence-${alias.id}`}
                type="text"
                value={agence}
                onChange={(evenement) => setAgence(evenement.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              />
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setModeCreation((valeur) => !valeur)}
            className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          >
            {modeCreation ? "Choisir un chantier existant" : "Créer un chantier"}
          </button>
          <button
            type="submit"
            disabled={!soumissionValide || validation.isPending}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Valider
          </button>
        </div>

        {validation.isError && (
          <p role="alert" className="text-sm text-red-700">
            {messageErreur(validation.error)}
          </p>
        )}
      </form>
    </li>
  );
}

/** Formulaire de validation d'un article (L3-D9) : champs pré-remplis avec
 * les valeurs proposées ; le ratio est saisi en texte et envoyé tel quel en
 * chaîne décimale, seule la virgule est remplacée par un point (décision du
 * contrôleur — aucune autre transformation, aucun calcul). */
function ArticleCarte({ article }: { article: ArticleAValider }): ReactElement {
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

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3">
        <p className="text-sm font-semibold text-slate-900">
          {article.code}
          {article.libelle !== null ? ` · ${article.libelle}` : ""}
        </p>
        <p className="text-xs text-slate-500">{article.fournisseur}</p>
      </div>

      <form onSubmit={soumettre} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <label
            htmlFor={`unite-cdt-${article.id}`}
            className="mb-1 block text-xs font-medium text-slate-700"
          >
            Unité de conditionnement
          </label>
          <input
            id={`unite-cdt-${article.id}`}
            type="text"
            value={uniteCdt}
            onChange={(evenement) => setUniteCdt(evenement.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          />
        </div>
        <div>
          <label
            htmlFor={`unite-fact-${article.id}`}
            className="mb-1 block text-xs font-medium text-slate-700"
          >
            Unité de facturation
          </label>
          <input
            id={`unite-fact-${article.id}`}
            type="text"
            value={uniteFact}
            onChange={(evenement) => setUniteFact(evenement.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          />
        </div>
        <div>
          <label
            htmlFor={`ratio-${article.id}`}
            className="mb-1 block text-xs font-medium text-slate-700"
          >
            Ratio
          </label>
          <input
            id={`ratio-${article.id}`}
            type="text"
            inputMode="decimal"
            value={ratio}
            onChange={(evenement) => setRatio(evenement.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          />
        </div>

        <div className="sm:col-span-3">
          <button
            type="submit"
            disabled={validation.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Valider
          </button>
          {validation.isError && (
            <p role="alert" className="mt-2 text-sm text-red-700">
              {validation.error instanceof ErreurApi
                ? validation.error.detail
                : "Une erreur est survenue, réessayez."}
            </p>
          )}
        </div>
      </form>
    </li>
  );
}

/** Écran « À traiter » de l'admin (L3-D18), mobile d'abord : anomalies
 * ouvertes de gravité haute (L4-D18, section ajoutée avant les documents),
 * documents « à vérifier » (BL, enlèvements, factures), alias chantier en
 * attente de validation et articles à valider. Réservé à l'admin par
 * `GardeAdmin` (voir `App.tsx`) : aucune vérification de rôle ici. Rafraîchi
 * toutes les 30 s (décision du contrôleur). */
export function ATraiter(): ReactElement {
  const aTraiter = useQuery({
    queryKey: CLE_A_TRAITER,
    queryFn: obtenirATraiter,
    refetchInterval: 30_000,
  });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });

  return (
    <div className="space-y-8">
      <h1 className="text-lg font-semibold text-slate-900">À traiter</h1>

      {aTraiter.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {aTraiter.isError && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger l'écran « À traiter ».
        </p>
      )}

      {aTraiter.data && (
        <>
          <section>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold text-slate-900">
                Anomalies à traiter ({aTraiter.data.anomalies_hautes.length})
              </h2>
              <Link
                to="/anomalies"
                className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              >
                Voir toutes les anomalies
              </Link>
            </div>
            <SectionAnomaliesHautes anomalies={aTraiter.data.anomalies_hautes} />
          </section>

          <section>
            <h2 className="mb-3 text-base font-semibold text-slate-900">
              Documents à vérifier ({aTraiter.data.documents.length})
            </h2>
            <SectionDocuments documents={aTraiter.data.documents} />
          </section>

          <section>
            <h2 className="mb-3 text-base font-semibold text-slate-900">
              Chantiers à rattacher ({aTraiter.data.alias.length})
            </h2>
            {aTraiter.data.alias.length === 0 ? (
              <p className="text-sm text-slate-600">Rien à traiter.</p>
            ) : (
              <ul className="space-y-3">
                {aTraiter.data.alias.map((alias) => (
                  <AliasCarte key={alias.id} alias={alias} chantiers={chantiers.data ?? []} />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="mb-3 text-base font-semibold text-slate-900">
              Articles à valider ({aTraiter.data.articles.length})
            </h2>
            {aTraiter.data.articles.length === 0 ? (
              <p className="text-sm text-slate-600">Rien à traiter.</p>
            ) : (
              <ul className="space-y-3">
                {aTraiter.data.articles.map((article) => (
                  <ArticleCarte key={article.id} article={article} />
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
