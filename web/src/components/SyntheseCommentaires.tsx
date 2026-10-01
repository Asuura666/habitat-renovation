import { type ReactElement } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  type ActionSynthese,
  cleSyntheseIA,
  lireSyntheseIA,
  marquerActionSynthese,
} from "../api/ia";
import { formaterJourMois, periodeSemaine, TIRET } from "../lib/formats";
import { Carte } from "../ui";

/** Compteurs de la semaine : commentaires et prix contestés, seulement ceux
 * qui existent ; « 0 commentaire » si aucun des deux. */
function texteCompteurs(nbCommentaires: number, nbContestations: number): string {
  const morceaux: string[] = [];
  if (nbCommentaires > 0) {
    morceaux.push(`${nbCommentaires} commentaire${nbCommentaires > 1 ? "s" : ""}`);
  }
  if (nbContestations > 0) {
    morceaux.push(`${nbContestations} contestation${nbContestations > 1 ? "s" : ""}`);
  }
  return morceaux.length > 0 ? morceaux.join(" · ") : "0 commentaire";
}

/** Carte « Commentaires de la semaine » de la Vue d'ensemble (T5, phase 4 IA,
 * spec §4.6) : synthèse hebdomadaire des commentaires rédigée par l'IA (T4,
 * `GET /api/ia/synthese`) et ses actions à cocher. Montée par une seule
 * ligne dans `pages/VueEnsemble.tsx`, indépendante du reste de l'accueil
 * (sa propre requête TanStack Query) : une panne ici n'empêche jamais
 * d'afficher les chiffres du mois, les chantiers ou les problèmes à
 * régler — brief T5, « rien de bloquant pour l'accueil ».
 *
 * Rappel CDC (« l'IA extrait et synthétise, elle ne décide jamais ») : le
 * résumé et les actions proposées sont affichés tels quels, jamais
 * retraités ici (pas de calcul, pas de tri autre que celui déjà fait côté
 * serveur) ; « Rédigé par l'IA — à vérifier » le rappelle à l'écran.
 *
 * Ne rend rien quand il n'y a ni synthèse ni IA active (brief T5) : un
 * client dont l'abonnement n'est pas encore branché (décision D6 de la
 * spec) ne doit jamais voir une carte vide sur son accueil.
 */
export function SyntheseCommentaires(): ReactElement | null {
  const synthese = useQuery({ queryKey: cleSyntheseIA, queryFn: lireSyntheseIA });

  if (synthese.isPending) {
    return (
      <p role="status" className="text-sm text-encre-2">
        Chargement des commentaires de la semaine…
      </p>
    );
  }

  if (synthese.isError) {
    // Discret, jamais bloquant (brief T5) : pas d'alerte mise en évidence,
    // ni gabarit de carte — un simple message, le reste de l'accueil
    // (chiffres, chantiers, à régler) s'affiche normalement à côté.
    return (
      <p className="text-sm text-encre-2">
        Impossible de charger les commentaires de la semaine pour l'instant.
      </p>
    );
  }

  const { ia_active: iaActive, derniere, encore_a_faire: encoreAFaire } = synthese.data;

  if (derniere === null && !iaActive) {
    return null;
  }

  const actionsCetteSemaine = derniere?.actions ?? [];

  return (
    <Carte
      titre="Commentaires de la semaine"
      action={
        // Jamais pour un statut « vide » (fix round 1) : ce message est
        // produit sans le moindre appel à l'IA (`ia_synthese.py::
        // _enregistrer_synthese_vide`) — l'afficher aurait fait croire à
        // une lecture par l'IA qui n'a jamais eu lieu.
        derniere !== null && derniere.statut !== "vide" ? (
          <span className="text-right text-xs text-encre-2">Rédigé par l'IA — à vérifier</span>
        ) : undefined
      }
    >
      <div className="space-y-4">
        {derniere !== null ? (
          <>
            <p className="text-sm text-encre-2">
              {periodeSemaine(derniere.semaine_debut, derniere.semaine_fin)}
            </p>
            {derniere.statut === "vide" ? (
              <p className="text-sm text-encre-2">{derniere.resume}</p>
            ) : (
              <>
                <p className="text-xs font-medium text-encre-2">
                  {texteCompteurs(derniere.nb_commentaires, derniere.nb_contestations)}
                </p>
                <TexteResume texte={derniere.resume} />
                {actionsCetteSemaine.length > 0 && (
                  <ul className="divide-y divide-bordure">
                    {actionsCetteSemaine.map((action) => (
                      <ActionLigne key={action.id} action={action} />
                    ))}
                  </ul>
                )}
              </>
            )}
          </>
        ) : (
          <p className="text-sm text-encre-2">
            La synthèse des commentaires de la semaine arrive chaque lundi matin.
          </p>
        )}

        {encoreAFaire.length > 0 && (
          <details className="group border-t border-bordure pt-3" open={actionsCetteSemaine.length === 0}>
            <summary className="inline-flex min-h-[44px] w-full cursor-pointer list-none items-center gap-2 text-sm font-semibold text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent">
              <span aria-hidden="true" className="inline-block transition-transform group-open:rotate-90">
                ▸
              </span>
              Encore à faire ({encoreAFaire.length})
            </summary>
            <ul className="mt-2 divide-y divide-bordure">
              {encoreAFaire.map((action) => (
                <ActionLigne key={action.id} action={action} afficherSemaine />
              ))}
            </ul>
          </details>
        )}
      </div>
    </Carte>
  );
}

/** Résumé de l'IA (« texte simple, paragraphes respectés », brief T5) : un
 * texte brut (`SCHEMA_SYNTHESE`, jamais de Markdown/HTML) dont les sauts de
 * ligne séparent des paragraphes — un `<p>` par paragraphe plutôt qu'un bloc
 * unique qui les aurait effondrés en un mur de texte. */
function TexteResume({ texte }: { texte: string }): ReactElement {
  const paragraphes = texte
    .split(/\n+/)
    .map((paragraphe) => paragraphe.trim())
    .filter((paragraphe) => paragraphe !== "");
  return (
    <div className="space-y-2 text-sm text-encre [overflow-wrap:anywhere]">
      {paragraphes.map((paragraphe, index) => (
        <p key={index}>{paragraphe}</p>
      ))}
    </div>
  );
}

/** Une action à cocher, dans les actions de la semaine ou « Encore à
 * faire » (`afficherSemaine`, brief T5 : « chacune avec sa semaine »).
 * Mutation propre à chaque ligne (même principe que
 * `CommentairesLignes.tsx::FormulaireAjoutCommentaire`) : deux actions
 * cochées en même temps ne se marchent pas dessus, chacune garde son propre
 * état d'envoi et son propre message d'erreur.
 *
 * Cible tactile 44 px (fix round 1) : le `<label>` lui-même porte
 * `min-h-[44px]` et enveloppe la case (même convention que
 * `FicheChantier.tsx::FormulaireEdition`, case « Chantier actif ») -- un
 * conteneur `min-h-[44px]` autour d'éléments plus petits ne suffit pas, la
 * zone cliquable réelle reste la taille de ces éléments, pas celle du
 * conteneur. Les liens « Bon … » restent hors du `<label>` (un `<li>`
 * frère, après) : un lien imbriqué dans un `<label>` transfère aussi un
 * clic à la case associée (comportement natif du navigateur), jamais voulu
 * ici -- imbriquer la case elle-même ne pose pas ce problème (elle est le
 * contrôle associé, pas un élément tiers). */
function ActionLigne({
  action,
  afficherSemaine = false,
}: {
  action: ActionSynthese;
  afficherSemaine?: boolean;
}): ReactElement {
  const queryClient = useQueryClient();
  const cochee = action.faite_le !== null;
  const mutation = useMutation({
    mutationFn: (faite: boolean) => marquerActionSynthese(action.id, faite),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cleSyntheseIA });
    },
  });
  const idCase = `action-synthese-${action.id}`;

  return (
    <li className="py-2.5">
      <label
        htmlFor={idCase}
        className="flex min-h-[44px] cursor-pointer items-center gap-3 text-sm text-encre"
      >
        <input
          id={idCase}
          type="checkbox"
          checked={cochee}
          disabled={mutation.isPending}
          onChange={() => mutation.mutate(!cochee)}
          className="h-5 w-5 shrink-0 rounded border-bordure text-accent outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        />
        <span className="flex-1">
          {afficherSemaine && (
            <span className="block text-xs text-encre-2">
              semaine du {formaterJourMois(action.semaine_debut)}
            </span>
          )}
          {action.texte}
        </span>
      </label>
      {cochee && (
        <p className="ml-8 text-xs text-encre-2">
          faite par {action.faite_par ?? TIRET} le {formaterJourMois(action.faite_le)}
        </p>
      )}
      {action.bons.length > 0 && (
        <p className="ml-8 mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {action.bons.map((bon) => (
            <Link
              key={bon.document_id}
              to={`/documents/${bon.document_id}`}
              className="text-xs font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {bon.numero !== null ? `Bon ${bon.numero}` : "Voir le bon"}
            </Link>
          ))}
        </p>
      )}
      {mutation.isError && (
        <p role="alert" className="ml-8 mt-1 text-xs text-alerte">
          L'envoi a échoué, réessayez.
        </p>
      )}
    </li>
  );
}
