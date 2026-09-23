import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { type BlocFacture, cleFacture, obtenirFacture } from "../api/factures";
import { formaterDate, formaterMontant, formaterQuantite, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";
import { Carte, FilAriane } from "../ui";

/** Mêmes badges que `DocumentsListe.tsx` (décision du contrôleur, L3-T9,
 * reprise Task 8) : dupliqués plutôt que partagés, comme le reste des
 * petits composants de présentation de ces pages. Couleurs reprises de
 * `ui/PastilleEtat.tsx` pour rester cohérent avec la charte (« Registre »,
 * spec §2 : jamais la couleur seule, toujours un libellé). */
function BadgeAVerifier(): ReactElement {
  return (
    <span className="inline-flex shrink-0 rounded-full bg-[#fbe9c6] px-2 py-0.5 text-xs font-medium text-[#7a4a00]">
      À vérifier
    </span>
  );
}

function BadgeConfianceReduite(): ReactElement {
  return (
    <span className="inline-flex shrink-0 rounded-full bg-[#fbe9c6] px-2 py-0.5 text-xs font-medium text-[#7a4a00]">
      Confiance réduite (lecture automatique)
    </span>
  );
}

function PastilleReception({ recu }: { recu: boolean }): ReactElement {
  const classes = recu ? "bg-[#e4f1ea] text-encre" : "bg-[#f9dedc] text-[#8c1d18]";
  return (
    <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {recu ? "Reçu" : "Non reçu"}
    </span>
  );
}

/** Une livraison de la facture (Task 8 : présentée comme une « livraison »,
 * jamais un « bloc » — spec §5, sans jargon visible). `id={`bloc-${bloc.id}`}`
 * est une ancre stable, ciblée depuis d'autres écrans (ex. l'écran « À
 * régler », `BilanFournisseur.tsx`) — conservée telle quelle malgré
 * l'habillage. */
function LivraisonCarte({ bloc }: { bloc: BlocFacture }): ReactElement {
  return (
    <li id={`bloc-${bloc.id}`} className="scroll-mt-4 rounded-carte border border-bordure bg-surface p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-encre">BL {bloc.numero_bl ?? "non détecté"}</p>
          <p className="text-xs text-encre-2">{formaterDate(bloc.date_bl)}</p>
        </div>
        <PastilleReception recu={bloc.bl_recu} />
      </div>

      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm text-encre sm:grid-cols-3">
        <div>
          <dt className="text-xs text-encre-2">Chantier (brut)</dt>
          <dd>{bloc.chantier_brut ?? TIRET}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Commande</dt>
          <dd>{bloc.numero_commande ?? TIRET}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Montant HT</dt>
          <dd className="font-mono">{formaterMontant(bloc.montant_ht)}</dd>
        </div>
      </dl>

      {bloc.commentaire && (
        <p className="mb-3 whitespace-pre-line text-sm text-encre-2">{bloc.commentaire}</p>
      )}

      {bloc.bl_recu && bloc.bl_document_id && (
        <a
          href={`/api/documents/${bloc.bl_document_id}/fichier`}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-3 inline-block text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Voir la photo
        </a>
      )}

      <details>
        <summary className="inline-flex min-h-[44px] cursor-pointer items-center text-sm font-medium text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Lignes ({bloc.lignes.length})
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[640px] divide-y divide-bordure text-sm">
            <caption className="sr-only">Lignes de cette livraison</caption>
            <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
              <tr>
                <th scope="col" className="px-3 py-2">Article</th>
                <th scope="col" className="px-3 py-2">Qté livrée</th>
                <th scope="col" className="px-3 py-2">Qté totale</th>
                <th scope="col" className="px-3 py-2">PU HT</th>
                <th scope="col" className="px-3 py-2">Remise</th>
                <th scope="col" className="px-3 py-2">Montant HT</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-bordure">
              {bloc.lignes.map((ligne) => (
                <tr key={ligne.ordre}>
                  <td className="px-3 py-2 text-encre">
                    {ligne.article_brut ?? ligne.code_brut ?? TIRET}
                  </td>
                  <td className="px-3 py-2 font-mono text-encre">{formaterQuantite(ligne.qte_livree)}</td>
                  <td className="px-3 py-2 font-mono text-encre">{formaterQuantite(ligne.qte_totale)}</td>
                  <td className="px-3 py-2 font-mono text-encre">{formaterMontant(ligne.pu_ht)}</td>
                  <td className="px-3 py-2 font-mono text-encre">
                    {ligne.remise_pct !== null ? `${ligne.remise_pct} %` : TIRET}
                  </td>
                  <td className="px-3 py-2 font-mono text-encre">{formaterMontant(ligne.montant_ht)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </li>
  );
}

/** `GET /api/factures/{id}` (décisions du contrôleur L2-T7, habillage et
 * vocabulaire Task 8 : montée depuis `/documents/:id` quand l'identifiant
 * est celui d'une facture — voir `PageBl.tsx`, qui délègue ici sur un 404
 * du document). Réservé à l'admin par `GardeAdmin` sur son ancienne route
 * `/factures/:id` (redirigée) — `/documents/:id` n'a pas de garde
 * explicite : un agent qui obtiendrait l'identifiant d'une facture (aucun
 * lien de l'application ne lui en donne un) recevrait de toute façon un 403
 * du serveur, traduit ci-dessous par « Facture introuvable. » (décision du
 * contrôleur, même repli qu'un 404 : jamais de détail technique affiché). */
export function FactureDetail(): ReactElement {
  const { id } = useParams<{ id: string }>();

  const facture = useQuery({
    queryKey: id !== undefined ? cleFacture(id) : ["factures", "sans-identifiant"],
    queryFn: () => obtenirFacture(id ?? ""),
    enabled: id !== undefined,
  });

  if (id === undefined) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Facture introuvable.
      </p>
    );
  }

  if (facture.isPending) {
    return (
      <p role="status" className="text-sm text-encre-2">
        Chargement…
      </p>
    );
  }

  if (facture.isError || !facture.data) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Facture introuvable.
      </p>
    );
  }

  const donnees = facture.data;
  const aDesBadges = donnees.statut === "a_verifier" || donnees.confiance_reduite;

  return (
    <div className="space-y-6">
      <FilAriane
        elements={[{ libelle: "Documents", vers: "/documents" }, { libelle: `Facture ${donnees.numero}` }]}
      />

      <header>
        <h1 className="font-titre text-2xl font-medium text-encre sm:text-3xl">
          Facture <span className="font-mono text-xl text-encre sm:text-2xl">{donnees.numero}</span>
        </h1>
        {aDesBadges && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {donnees.statut === "a_verifier" && <BadgeAVerifier />}
            {donnees.confiance_reduite && <BadgeConfianceReduite />}
          </div>
        )}
      </header>

      <Carte>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm text-encre sm:grid-cols-4">
          <div>
            <dt className="text-xs text-encre-2">Fournisseur</dt>
            <dd>{donnees.fournisseur}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Date</dt>
            <dd className="font-mono">{formaterDate(donnees.date_doc)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Total HT</dt>
            <dd className="font-mono">{formaterMontant(donnees.total_ht)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Déposée par</dt>
            <dd>{donnees.deposant ?? TIRET}</dd>
          </div>
        </dl>
        <a
          href={`/api/factures/${donnees.id}/fichier`}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 inline-block text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Voir le PDF
        </a>
      </Carte>

      {donnees.statut === "a_verifier" && donnees.motifs.length > 0 && (
        <div className="rounded-lg border border-ecart/40 bg-[#fbe9c6] p-4">
          <h2 className="mb-2 text-sm font-semibold text-[#7a4a00]">
            Pourquoi une vérification est demandée
          </h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-[#7a4a00]">
            {donnees.motifs.map((motif, index) => (
              <li key={index}>{libelleMotif(motif)}</li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h2 className="mb-3 font-titre text-lg font-medium text-encre">
          Livraisons ({donnees.blocs.length})
        </h2>
        <ul className="space-y-4">
          {donnees.blocs.map((bloc) => (
            <LivraisonCarte key={bloc.id} bloc={bloc} />
          ))}
        </ul>
      </div>
    </div>
  );
}
