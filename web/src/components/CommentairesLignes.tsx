import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErreurApi } from "../api/client";
import {
  type CommentaireLigne,
  type LigneCommentee,
  ajouterCommentaire,
  cleCommentaires,
  lireCommentaires,
} from "../api/commentaires";
import { gererEntreeCommentaire } from "../lib/entreeClavier";
import { formaterDateHeure, formaterQuantite, TIRET } from "../lib/formats";
import { EtatVide } from "../ui";

const LONGUEUR_COMMENTAIRE_MAX = 1000;

/** Message d'erreur en français courant pour l'échec de l'envoi d'un
 * commentaire (spec §6), sur le modèle de
 * `pages/ProblemeDetail.tsx::messageErreurTraitement` : jamais le détail
 * technique du serveur (`ErreurApi.detail`) affiché tel quel. */
function messageErreurAjout(erreur: unknown): string {
  if (erreur instanceof ErreurApi && erreur.status === 422) {
    return "Le commentaire doit contenir entre 1 et 1 000 caractères.";
  }
  if (erreur instanceof ErreurApi && erreur.status === 404) {
    return "Cette ligne n'existe plus : la lecture du bon a peut-être été refaite. Rechargez la page.";
  }
  return "L'envoi a échoué, réessayez.";
}

/** Un commentaire déjà enregistré (« Léa, 27/09/2026 14:05 — texte »,
 * maquette de la spec §6) — même formateur de date/heure que le reste de
 * l'application (`formaterDateHeure`), jamais un identifiant technique. */
function LigneDeCommentaire({ commentaire }: { commentaire: CommentaireLigne }): ReactElement {
  return (
    <li className="[overflow-wrap:anywhere]">
      <span className="font-medium text-encre">{commentaire.auteur ?? TIRET}</span>
      {", "}
      {formaterDateHeure(commentaire.cree_le)}
      {" — "}
      {commentaire.texte}
    </li>
  );
}

/** Formulaire d'ajout d'un commentaire, ouvert pour une seule ligne à la
 * fois (décision du contrôleur, même simplicité que le commentaire
 * d'archivage de `pages/DocumentDetail.tsx`) : compteur de caractères,
 * bouton désactivé tant que le texte est vide ou que l'envoi est en cours,
 * message d'erreur en français courant si l'envoi échoue (ligne disparue
 * entre-temps -> 404, texte invalide -> 422 — voir
 * `ingest/commentaires.py`). Refermé et invalidé par l'appelant
 * (`onEnregistre`), jamais ici : ce composant ne connaît pas la clé de
 * cache de la liste. */
function FormulaireAjoutCommentaire({
  ligneId,
  onAnnuler,
  onEnregistre,
}: {
  ligneId: string;
  onAnnuler: () => void;
  onEnregistre: () => void;
}): ReactElement {
  const [texte, setTexte] = useState("");
  const mutation = useMutation({
    mutationFn: () => ajouterCommentaire(ligneId, texte),
    onSuccess: onEnregistre,
  });

  const envoiPossible = texte.trim() !== "" && !mutation.isPending;

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    mutation.mutate();
  }

  /** Entrée sur ordinateur (`lib/entreeClavier.ts`) : mêmes conditions que
   * le bouton « Enregistrer ». */
  function enregistrerAuClavier(): void {
    if (envoiPossible) {
      mutation.mutate();
    }
  }

  return (
    <form onSubmit={soumettre} className="mt-2 space-y-2 rounded-lg border border-bordure bg-fond p-3">
      <label htmlFor={`commentaire-${ligneId}`} className="sr-only">
        Commentaire
      </label>
      <textarea
        id={`commentaire-${ligneId}`}
        value={texte}
        onChange={(evenement) => setTexte(evenement.target.value)}
        onKeyDown={(evenement) => gererEntreeCommentaire(evenement, enregistrerAuClavier, setTexte)}
        maxLength={LONGUEUR_COMMENTAIRE_MAX}
        rows={2}
        autoFocus
        className="w-full rounded-md border border-bordure bg-surface px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-encre-2">
          {texte.length}/{LONGUEUR_COMMENTAIRE_MAX} caractères
          <span className="hidden [@media(hover:hover)_and_(pointer:fine)]:inline">
            {" · Entrée pour enregistrer, Maj+Entrée pour aller à la ligne"}
          </span>
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onAnnuler}
            className="inline-flex min-h-[44px] items-center text-sm font-medium text-encre-2 underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Annuler
          </button>
          <button
            type="submit"
            disabled={!envoiPossible}
            className="inline-flex min-h-[44px] items-center rounded-md bg-accent px-4 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Enregistrer
          </button>
        </div>
      </div>
      {mutation.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreurAjout(mutation.error)}
        </p>
      )}
    </form>
  );
}

/** Une ligne du bon (désignation, code en petit, quantité — spec §6) avec
 * ses commentaires du plus ancien au plus récent (déjà dans cet ordre côté
 * serveur, `ingest/commentaires.py::commentaires_du_bon`), puis le lien
 * d'ajout ou le formulaire ouvert. */
function EntreeLigne({
  ligne,
  ouverte,
  onOuvrir,
  onFermer,
  onEnregistre,
}: {
  ligne: LigneCommentee;
  ouverte: boolean;
  onOuvrir: () => void;
  onFermer: () => void;
  onEnregistre: () => void;
}): ReactElement {
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div>
          <p className="font-medium text-encre">{ligne.article ?? ligne.code ?? TIRET}</p>
          {ligne.code !== null && ligne.article !== null && (
            <p className="font-mono text-xs text-encre-2">{ligne.code}</p>
          )}
        </div>
        <p className="shrink-0 font-mono text-sm text-encre-2">
          {formaterQuantite(ligne.quantite)} {ligne.unite ?? ""}
        </p>
      </div>
      {ligne.commentaires.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-encre-2">
          {ligne.commentaires.map((commentaire) => (
            <LigneDeCommentaire key={commentaire.id} commentaire={commentaire} />
          ))}
        </ul>
      )}
      {ouverte ? (
        <FormulaireAjoutCommentaire ligneId={ligne.ligne_id} onAnnuler={onFermer} onEnregistre={onEnregistre} />
      ) : (
        <button
          type="button"
          onClick={onOuvrir}
          className="mt-2 inline-flex min-h-[44px] items-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Ajouter un commentaire
        </button>
      )}
    </li>
  );
}

/** Un commentaire dont la ligne a disparu (relance de la lecture, ou
 * correction qui a supprimé la ligne — `ligne_id` alors `NULL` côté
 * serveur, `ON DELETE SET NULL`) : seul son libellé figé au moment de
 * l'ajout permet encore de savoir de quoi il parlait (spec §6, « Commentaires
 * sur des lignes modifiées depuis »). Jamais de formulaire ici : on ne peut
 * plus commenter une ligne qui n'existe plus. */
function CommentaireSansLigne({ commentaire }: { commentaire: CommentaireLigne }): ReactElement {
  return (
    <li className="py-3 text-sm [overflow-wrap:anywhere]">
      <p className="text-encre">{commentaire.ligne_libelle}</p>
      <p className="mt-1 text-encre-2">
        <span className="font-medium text-encre">{commentaire.auteur ?? TIRET}</span>
        {", "}
        {formaterDateHeure(commentaire.cree_le)}
        {" — "}
        {commentaire.texte}
      </p>
    </li>
  );
}

/** Carte « Commentaires (N) » de la page BL (spec §6 de
 * `docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md`),
 * montée pour l'admin comme pour l'agent (décision d'Ilane du 27/09/2026) :
 * une entrée par ligne du bon avec ses commentaires et un lien pour en
 * ajouter un, puis les commentaires dont la ligne a disparu. Repliable
 * comme « Corriger la lecture du bon » (`pages/PageBl.tsx::SectionCorrection`,
 * mêmes classes), ouverte d'office s'il y a déjà des commentaires — jamais
 * de tableau (téléphone d'abord, cibles de 44 px). Une seule ligne peut
 * avoir son formulaire d'ajout ouvert à la fois (`ligneOuverte`, décision du
 * contrôleur, simplicité §« Méthode » de `CLAUDE.md`). */
export function CommentairesLignes({ documentId }: { documentId: string }): ReactElement {
  const queryClient = useQueryClient();
  const [ligneOuverte, setLigneOuverte] = useState<string | null>(null);

  const commentaires = useQuery({
    queryKey: cleCommentaires(documentId),
    queryFn: () => lireCommentaires(documentId),
  });

  function surEnregistrement(): void {
    setLigneOuverte(null);
    void queryClient.invalidateQueries({ queryKey: cleCommentaires(documentId) });
  }

  if (commentaires.isPending) {
    return (
      <div className="rounded-carte border border-bordure bg-surface p-5">
        <p role="status" className="text-sm text-encre-2">
          Chargement des commentaires…
        </p>
      </div>
    );
  }

  if (commentaires.isError) {
    return (
      <div className="rounded-carte border border-bordure bg-surface p-5">
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les commentaires.
        </p>
      </div>
    );
  }

  const donnees = commentaires.data;

  return (
    <details
      className="group rounded-carte border border-bordure bg-surface p-5"
      open={donnees.nb_commentaires > 0}
    >
      <summary className="inline-flex min-h-[44px] w-full cursor-pointer list-none items-center gap-2 text-sm font-semibold text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <span aria-hidden="true" className="inline-block transition-transform group-open:rotate-90">
          ▸
        </span>
        Commentaires ({donnees.nb_commentaires})
      </summary>
      <div className="mt-4">
        {donnees.lignes.length === 0 ? (
          <EtatVide message="Aucune ligne sur ce bon." />
        ) : (
          <ul className="divide-y divide-bordure">
            {donnees.lignes.map((ligne) => (
              <EntreeLigne
                key={ligne.ligne_id}
                ligne={ligne}
                ouverte={ligneOuverte === ligne.ligne_id}
                onOuvrir={() => setLigneOuverte(ligne.ligne_id)}
                onFermer={() => setLigneOuverte(null)}
                onEnregistre={surEnregistrement}
              />
            ))}
          </ul>
        )}

        {donnees.sans_ligne.length > 0 && (
          <div className="mt-4 border-t border-bordure pt-4">
            <h3 className="text-sm font-semibold text-encre">Commentaires sur des lignes modifiées depuis</h3>
            <ul className="mt-2 divide-y divide-bordure">
              {donnees.sans_ligne.map((commentaire) => (
                <CommentaireSansLigne key={commentaire.id} commentaire={commentaire} />
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
