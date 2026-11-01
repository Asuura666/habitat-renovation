import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { cleLivraisons, type FiltresLivraisons, type LigneLivraison, listerLivraisons, urlExportLivraisons } from "../api/bilan";
import { type LivraisonAffichee, TableauLivraisons } from "../components/TableauLivraisons";
import { libelleMois, lireMois, moisApi } from "../lib/formats";
import { EnTetePage } from "../ui";

const CLASSES_CHAMP_MOIS =
  "min-h-[44px] rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";

/** Une ligne de `GET /api/bilan/livraisons`, mise à la forme attendue par
 * `TableauLivraisons` -- chantier et fournisseur varient tous les deux ici
 * (`colonneChantier`), contrairement à la fiche chantier (chantier fixé par
 * l'URL) ou à la fiche fournisseur (fournisseur fixé). */
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

/**
 * Livraisons (Task 13, mise en production du 1er octobre, spec §4.3) :
 * point d'arrivée des montants « Conforme » cliquables de l'accueil, de la
 * fiche chantier et de la fiche fournisseur -- accessible aussi seule
 * (`?mois=`, `?agence=`, `?chantier=`, `?fournisseur=`, `?etat=`, tous
 * facultatifs), pour la même liste de livraisons que ces trois écrans
 * (`GET /api/bilan/livraisons`, mêmes montants que `bilan_par_bl`, jamais
 * une nouvelle définition de « conforme »). Réservé à l'admin (`GardeAdmin`,
 * voir `App.tsx`).
 *
 * Le nom du chantier/fournisseur filtré (quand `?chantier=`/`?fournisseur=`
 * est présent) est lu sur la première ligne renvoyée plutôt que par un
 * second appel réseau au référentiel : toutes les lignes d'un chantier ou
 * d'un fournisseur filtré partagent le même nom.
 */
export function Livraisons(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const mois = lireMois(parametres.get("mois"));
  const agence = parametres.get("agence") || undefined;
  const chantierId = parametres.get("chantier") || undefined;
  const fournisseurId = parametres.get("fournisseur") || undefined;

  const filtres: FiltresLivraisons = {
    mois: mois !== undefined ? moisApi(mois) : undefined,
    agence,
    chantierId,
    fournisseurId,
  };

  const livraisonsQuery = useQuery({
    queryKey: cleLivraisons(filtres),
    queryFn: () => listerLivraisons(filtres),
  });

  const livraisons: LivraisonAffichee[] = (livraisonsQuery.data ?? []).map(versLivraisonAffichee);
  const nomChantierFiltre = chantierId !== undefined ? livraisons[0]?.chantier : undefined;
  const nomFournisseurFiltre = fournisseurId !== undefined ? livraisons[0]?.fournisseur : undefined;

  function changerMois(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur.trim() === "") {
      suivants.delete("mois");
    } else {
      suivants.set("mois", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  const periode = mois !== undefined ? libelleMois(mois) : "Tous les mois";
  const surtitre = [periode, nomChantierFiltre, nomFournisseurFiltre, agence !== undefined ? `Agence ${agence}` : undefined]
    .filter((valeur): valeur is string => valeur !== undefined)
    .join(" · ");
  const messageVide = mois !== undefined ? `Aucune livraison en ${periode}.` : "Aucune livraison pour ces filtres.";

  return (
    <div className="space-y-6">
      <EnTetePage
        surtitre={surtitre}
        titre="Livraisons"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={urlExportLivraisons(filtres)}
              className="inline-flex min-h-[44px] items-center rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              Exporter pour Excel
            </a>
            <label htmlFor="filtre-mois" className="text-sm text-encre-2">
              Mois
            </label>
            <input
              id="filtre-mois"
              type="month"
              value={mois ?? ""}
              onChange={(evenement) => changerMois(evenement.target.value)}
              className={CLASSES_CHAMP_MOIS}
            />
          </div>
        }
      />

      {livraisonsQuery.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {livraisonsQuery.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les livraisons.
        </p>
      )}
      {livraisonsQuery.isSuccess && (
        <TableauLivraisons livraisons={livraisons} colonneChantier messageVide={messageVide} />
      )}
    </div>
  );
}
