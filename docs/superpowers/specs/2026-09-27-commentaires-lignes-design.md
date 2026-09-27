# Commentaires sur les lignes de bons — conception (27/09/2026)

Tâche C de la phase 3 (`docs/roadmap-octobre-2026.md` §6.2), point 6 de la
demande du client (§1.1). Session B, branche `feature/phase-3-prix`.
**À valider par Ilane avant toute implémentation.**

## 1. Demande et décisions

Demande (verbatim, §1.1 point 6) : « Pouvoir ajouter un commentaire sur
chaque ligne de BL. » La synthèse hebdomadaire par une IA viendra en phase 4 :
rien ici ne la prépare au-delà de données propres et datées.

Décisions d'Ilane (27/09/2026, question §6.3-8) :

- tout compte connecté qui voit la page du bon peut commenter : admin comme
  agent (un agent ne voit que les bons qu'il a déposés, règle existante de
  `detail_document`) ;
- un commentaire n'est **ni modifiable ni supprimable** : pour se corriger, on
  en ajoute un autre ;
- chaque ajout est journalisé (`commentaire_ajoute`).

## 2. Ce qui existe et contraint la conception

- Les lignes d'un bon (`ligne`) sont **supprimées puis recréées** à chaque
  lecture ou relance de la lecture (`extraction_bl.enregistrer_extraction_bl`,
  `delete(Ligne)`), et une correction manuelle peut en supprimer
  (`corrections.corriger_lignes`). Une clé étrangère en cascade ferait donc
  disparaître des commentaires sans que personne ne l'ait voulu.
- La page du bon (`web/src/pages/PageBl.tsx`) est aussi modifiée par la
  session A (légende, chantier) : on n'y ajoute qu'**une ligne** qui monte un
  composant logé dans son propre fichier.

## 3. Données — migration `0012`

Nouvelle table `commentaire` (append-only, comme `journal`) :

| Colonne | Type | Rôle |
| --- | --- | --- |
| `id` | UUID, clé | |
| `document_id` | UUID, non nul, FK `document.id` `ON DELETE CASCADE` | bon commenté ; garde le commentaire rattaché au bon même si sa ligne disparaît |
| `ligne_id` | UUID, nullable, FK `ligne.id` `ON DELETE SET NULL` | ligne commentée ; devient vide si la ligne est supprimée |
| `ligne_libelle` | texte, non nul | libellé de la ligne au moment du commentaire (« code — désignation ») ; permet d'afficher un commentaire dont la ligne a disparu |
| `auteur_id` | UUID, nullable, FK `utilisateur.id` | comme `journal.utilisateur_id` |
| `texte` | texte, non nul, 1 à 1 000 caractères (contrôle `CHECK`) | |
| `created_at` | horodatage, défaut `now()` | |

Index sur `document_id`. Pas de colonne `updated_*` : aucune modification
n'est prévue. Aucune route ne modifie ni ne supprime un commentaire. Pas de
déclencheur qui refuserait les modifications : la mise à vide de `ligne_id`
par la base en est une, et la roadmap n'exige ce verrou que pour l'historique
des prix. Noté dans `docs/dette.md`.

## 4. Service (`app/modules/ingest/commentaires.py`)

- `commentaires_du_bon(session, document_id, *, utilisateur_id, role) ->
  CommentairesBon` : même règle de visibilité que `detail_document` (bl ou
  enlèvement ; un agent ne voit que ses dépôts ; sinon `DocumentIntrouvable`,
  jamais un 403). Renvoie :
  - `nb_commentaires` ;
  - `lignes` : toutes les lignes du bon dans l'ordre (`ordre`), chacune avec
    `ligne_id`, `code`, `article`, `quantite` (`qte_totale`), `unite` et ses
    commentaires, du plus ancien au plus récent (`auteur` = nom, sinon
    e-mail ; `texte` ; `cree_le`) ;
  - `sans_ligne` : les commentaires dont la ligne a disparu, avec leur
    `ligne_libelle`.
- `ajouter_commentaire(session, ligne_id, texte, *, utilisateur_id, role) ->
  CommentaireLu` : retrouve la ligne, puis son document, avec la même règle
  de visibilité (ligne inconnue ou invisible : `LigneIntrouvable`, 404).
  `texte` est nettoyé (`strip()`). S'il est vide ou dépasse 1 000
  caractères : `CommentaireInvalide` (422). Insère le commentaire (en figeant
  `ligne_libelle`) et une entrée de journal dans la même transaction :
  `action="commentaire_ajoute"`, `cible_table="commentaire"`,
  `cible_id=<id>`, `apres={"document_id", "numero", "ligne", "texte"}`.
  Commit.
- Les factures ne sont pas concernées : la demande porte sur les lignes de
  BL (et d'enlèvement, traité comme un BL, CDC §4.5).

## 5. API (`app/modules/api/commentaires.py`)

| Route | Accès | Réponse |
| --- | --- | --- |
| `GET /api/commentaires/documents/{document_id}` | tout compte connecté | `CommentairesBonReponse` ; 404 si invisible |
| `POST /api/commentaires/lignes/{ligne_id}` corps `{"texte": str}` | tout compte connecté | 201, `CommentaireReponse` ; 404 ; 422 |

Le routeur valide, appelle le service et sérialise ; il est enregistré dans
`app/modules/api/__init__.py` (une ligne). Le `POST` passe par le contrôle
d'origine existant, comme toute écriture.

## 6. Écran

Nouveau composant `web/src/components/CommentairesLignes.tsx`, monté par une
seule ligne en bas de `PageBl.tsx`, pour l'admin comme pour l'agent :

- carte « Commentaires (N) » repliable, ouverte d'office s'il y en a ;
- une entrée par ligne du bon : désignation (code en petit), quantité ; en
  dessous, ses commentaires (« Léa, 27/09 à 14:05 — texte ») ; puis un lien
  « Ajouter un commentaire » qui ouvre une zone de texte (1 000 caractères
  au plus, compteur) et un bouton « Enregistrer » ;
- sous le titre « Commentaires sur des lignes modifiées depuis » :
  les commentaires sans ligne, avec le libellé figé ;
- après l'enregistrement : invalidation de la requête, zone refermée ;
  message d'erreur en français courant si l'envoi échoue ;
- téléphone d'abord : cibles de 44 px, pas de tableau.

Journal (`web/src/lib/journal.ts`) : libellé « Commentaire ajouté », et le
détail affiché (ligne, texte) sans identifiant technique.

## 7. Tests

- Service (base) : ajout et lecture ; ordre des lignes et des commentaires ;
  texte vide ou trop long refusé ; un agent ne commente ni ne lit le bon d'un
  autre (introuvable) ; une facture est introuvable ; entrée de journal
  écrite ; **relance de la lecture** : le commentaire survit dans
  `sans_ligne` avec son libellé ; correction qui garde la ligne : le
  commentaire reste sur la ligne.
- API : 201/404/422, accès sans session refusé (401), agent sur son propre
  bon accepté.
- Migration : la chaîne reste linéaire (`tests/test_migrations.py`) ; le
  `CHECK` de longueur refuse un texte vide.
- Frontières : `tests/test_frontieres.py` inchangé et vert.
- Front : typecheck et build ; vérification visuelle sur téléphone et
  ordinateur.

## 8. Hors périmètre

Synthèse IA hebdomadaire et affichage sur la page d'accueil (phase 4) ;
commentaire sur le bon entier ou sur une facture ; modification ou
suppression ; notification ; nombre de commentaires dans la liste des
documents (possible plus tard si utile).
