import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import {
  cleBilanFournisseurs,
  type LigneBilanChantier,
  listerBilanChantiersFournisseur,
  listerBilanFournisseursGlobal,
  urlExportBilanChantiersFournisseur,
} from "../api/bilan";
import { type Anomalie, cleAnomalies, listerAnomalies } from "../api/anomalies";
import { CLE_FOURNISSEURS, listerFournisseurs } from "../api/referentiels";
import { formaterMontant } from "../lib/formats";
import { Chiffre, EnTetePage, EtatVide, FilAriane, phraseProbleme, titreRegle, urgence } from "../ui";

const CLASSES_BOUTON_LIEN =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

const CLASSES_LIEN_NOM =
  "font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

const CLASSES_CARTE = "rounded-carte border border-bordure bg-surface p-5";

/** Fond/texte de la pastille d'urgence (mêmes teintes que `ui/PastilleEtat
 * .tsx` pour « à rattacher »/« bl manquant » et « prix »/« quantités » —
 * aucun jeton Tailwind dédié pour ces fonds clairs, même limite déjà
 * assumée dans ce fichier partagé). `urgence` (Urgent/À voir/Info, spec §5)
 * n'est pas le même axe que `Etat` de `PastilleEtat` (état agrégé d'un
 * chantier) : composant local, pas de détournement de `PastilleEtat`. */
const CLASSES_URGENCE: Record<ReturnType<typeof urgence>, string> = {
  Urgent: "bg-[#f9dedc] text-[#8c1d18]",
  "À voir": "bg-[#fbe9c6] text-[#7a4a00]",
  Info: "bg-fond text-encre-2",
};

function NomChantier({ ligne }: { ligne: LigneBilanChantier }): ReactElement {
  const nom = ligne.nom_canonique ?? "Chantier non résolu";
  if (ligne.chantier_id === null) {
    return <>{nom}</>;
  }
  return (
    <Link to={`/chantiers/${ligne.chantier_id}`} className={CLASSES_LIEN_NOM}>
      {nom}
    </Link>
  );
}

function CarteChantierConcerne({ ligne }: { ligne: LigneBilanChantier }): ReactElement {
  return (
    <li className="rounded-carte border border-bordure bg-fond p-4">
      <h3 className="mb-3 font-medium text-encre">
        <NomChantier ligne={ligne} />
      </h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Facturé</dt>
          <dd className="mt-0.5 font-mono font-medium text-encre">
            {formaterMontant(ligne.montants.facture_ht)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Écart</dt>
          <dd className="mt-0.5 font-mono font-medium text-ecart-texte">
            {formaterMontant(ligne.montants.en_ecart)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Sans bon</dt>
          <dd className="mt-0.5 font-mono font-medium text-alerte">
            {formaterMontant(ligne.montants.non_justifie)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Problèmes</dt>
          <dd className="mt-0.5 font-medium text-encre">{ligne.montants.nb_anomalies_ouvertes}</dd>
        </div>
      </dl>
    </li>
  );
}

function SectionChantiersConcernes({ lignes }: { lignes: LigneBilanChantier[] }): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun chantier concerné pour l'instant." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md, spec §7). */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <CarteChantierConcerne key={ligne.chantier_id ?? "non-resolu"} ligne={ligne} />
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
                  <NomChantier ligne={ligne} />
                </th>
                <td className="px-5 py-3 text-right font-mono text-encre">
                  {formaterMontant(ligne.montants.facture_ht)}
                </td>
                <td className="px-5 py-3 text-right font-mono text-ecart-texte">
                  {formaterMontant(ligne.montants.en_ecart)}
                </td>
                <td className="px-5 py-3 text-right font-mono text-alerte">
                  {formaterMontant(ligne.montants.non_justifie)}
                </td>
                <td className="px-5 py-3 text-right text-encre">
                  {ligne.montants.nb_anomalies_ouvertes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Une ligne « problème ouvert » (spec §5) : titre et phrase chiffrée via le
 * langage courant partagé (`ui/libelles.ts`), jamais de code de règle brut
 * ; ouvre le détail du problème sur l'écran « À régler » (Task 6). */
function CarteProbleme({ anomalie }: { anomalie: Anomalie }): ReactElement {
  const niveau = urgence(anomalie.gravite);
  return (
    <li>
      <Link
        to={`/a-regler/${anomalie.id}`}
        className="block rounded-carte border border-bordure bg-fond px-4 py-3 outline-none transition-colors hover:bg-surface focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="mb-1 flex flex-wrap items-start justify-between gap-2">
          <span className="font-medium text-encre">{titreRegle(anomalie.regle)}</span>
          <span
            className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${CLASSES_URGENCE[niveau]}`}
          >
            {niveau}
          </span>
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
 * Fiche fournisseur (spec §4, Task 9) : trois `Chiffre` (Facturé, Écart
 * prix ou quantité, Sans bon de livraison — mêmes montants que les colonnes
 * de `FournisseursListe`, jamais un quatrième recalculé côté front),
 * chantiers concernés (lien `/chantiers/:id`), problèmes ouverts (lien
 * `/a-regler/:id`), agences connues et export CSV.
 *
 * Les trois chiffres viennent de la même requête que la liste
 * (`GET /api/bilan/fournisseurs`, toutes périodes) — pas de route dédiée à
 * un seul fournisseur côté serveur (voir `app/modules/api/bilan.py`) : la
 * ligne correspondante y est retrouvée par son identifiant, une simple
 * recherche, jamais une somme ni un recalcul. Le nom et les agences
 * viennent de `GET /api/fournisseurs` (référentiel), seule source qui
 * connaît un fournisseur même sans aucune facture.
 */
export function FicheFournisseur(): ReactElement {
  const { fournisseurId } = useParams();

  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });
  const bilanGlobal = useQuery({
    queryKey: cleBilanFournisseurs(null, {}),
    queryFn: () => listerBilanFournisseursGlobal({}),
  });
  const chantiers = useQuery({
    queryKey: ["bilan", "chantiers-fournisseur", fournisseurId, {}] as const,
    queryFn: () => listerBilanChantiersFournisseur(fournisseurId ?? "", {}),
    enabled: fournisseurId !== undefined,
  });
  const anomalies = useQuery({
    queryKey: cleAnomalies({ fournisseurId }),
    queryFn: () => listerAnomalies({ fournisseurId }),
    enabled: fournisseurId !== undefined,
  });

  const fournisseur = fournisseurs.data?.find((f) => f.id === fournisseurId);
  const ligneMontants = bilanGlobal.data?.find((l) => l.fournisseur_id === fournisseurId);
  const nom = fournisseur?.nom ?? ligneMontants?.nom ?? "Fournisseur";

  const chargementEntete = fournisseurs.isPending || bilanGlobal.isPending;
  const erreurEntete = fournisseurs.isError || bilanGlobal.isError;

  return (
    <div className="space-y-6">
      <FilAriane elements={[{ libelle: "Fournisseurs", vers: "/fournisseurs" }, { libelle: nom }]} />

      <EnTetePage
        titre={nom}
        actions={
          <a
            href={urlExportBilanChantiersFournisseur(fournisseurId ?? "", {})}
            className={CLASSES_BOUTON_LIEN}
          >
            Exporter en CSV
          </a>
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
            <section
              aria-label="Chiffres du fournisseur"
              className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4"
            >
              <Chiffre libelle="Facturé" valeur={formaterMontant(ligneMontants.montants.facture_ht)} />
              <Chiffre
                libelle="Écart prix ou quantité"
                valeur={formaterMontant(ligneMontants.montants.en_ecart)}
                ton="ecart"
              />
              <Chiffre
                libelle="Sans bon de livraison"
                valeur={formaterMontant(ligneMontants.montants.non_justifie)}
                ton="alerte"
              />
            </section>
          ) : (
            <EtatVide message="Aucune facture enregistrée pour ce fournisseur." />
          )}

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
            {chantiers.data && <SectionChantiersConcernes lignes={chantiers.data} />}
          </section>

          <section aria-label="Problèmes ouverts" className={CLASSES_CARTE}>
            <h2 className="mb-4 font-titre text-xl font-medium text-encre">
              Problèmes ouverts{anomalies.data ? ` · ${anomalies.data.length}` : ""}
            </h2>
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
