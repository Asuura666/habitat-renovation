# Commentaires sur les lignes de bons — plan d'exécution

Spec : `docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md`.
Branche : `feature/phase-3-prix` (session B). Trois tâches, un commit
chacune, dans l'ordre. **Aucune implémentation avant le « go » d'Ilane.**

## Contraintes communes

- `CLAUDE.md` fait foi : `api` n'importe que `ingest` et `app.core` ; le
  routeur valide, appelle le service, sérialise ; aucune règle dans le front.
- Numéros réservés à la session B : migration `0012`, action
  `commentaire_ajoute`, routes `/api/commentaires/…`.
- Fichiers partagés avec la session A (`PageBl.tsx`, `api/__init__.py`,
  `lib/journal.ts`, `openapi.json`, `schema.d.ts`) : ajout à la suite, une
  ligne quand c'est possible, rien de réorganisé.
- Données de test inventées uniquement. Textes à l'écran en français
  courant.
- Avant chaque commit : `uv run ruff check`, `uv run ruff format --check`,
  `uv run mypy`, `flock /tmp/habitat_reno-tests.lock uv run pytest`,
  `npm --prefix web run typecheck`, `npm --prefix web run build`. Le hook
  pre-commit les rejoue ; jamais `--no-verify`.
- Sous-agents Sonnet, un implémenteur à la fois ; chaque tâche est relue
  (conformité à la spec, puis qualité) avant la suivante.

## Task C1 : table `commentaire` (migration 0012)

**Fichiers**
- Créer `migrations/versions/0012_commentaire.py` (`down_revision = "0011"`).
- Modifier `app/modules/ingest/models.py` : classe `Commentaire` ajoutée
  après `Journal`.
- Tests : `tests/test_migrations.py` (15 → 16 tables) ; nouveau
  `app/modules/ingest/tests/test_commentaires.py` (premiers tests de
  contraintes).

**Contenu**
- Colonnes, clés et contraintes exactement comme la spec §3 :
  `document_id` `ON DELETE CASCADE`, `ligne_id` `ON DELETE SET NULL`,
  `CHECK (char_length(texte) BETWEEN 1 AND 1000)` nommé
  `ck_commentaire_texte_longueur`, index `ix_commentaire_document_id`.
- `downgrade()` supprime index puis table.

**Tests (écrits d'abord)**
- upgrade → downgrade → upgrade sans erreur (test existant) ;
- insérer un commentaire au texte vide lève `IntegrityError` ;
- supprimer la ligne commentée laisse le commentaire avec `ligne_id` nul.

**Commit** : `ingest: table des commentaires de lignes (migration 0012)`.

## Task C2 : service et API

**Fichiers**
- Créer `app/modules/ingest/commentaires.py` : dataclasses
  `CommentaireLu`, `LigneCommentee`, `CommentairesBon` ; exceptions
  `LigneIntrouvable`, `CommentaireInvalide` ; `LONGUEUR_COMMENTAIRE_MAX =
  1000` ; fonctions `commentaires_du_bon` et `ajouter_commentaire` (spec §4).
  Réutiliser `DocumentIntrouvable` (`ingest/lecture.py`).
- Créer `app/modules/api/commentaires.py` ; schémas Pydantic dans
  `app/modules/api/schemas.py` (à la fin) ; une ligne dans
  `app/modules/api/__init__.py`.
- Tests : `app/modules/ingest/tests/test_commentaires.py` (suite) ;
  `app/modules/api/tests/test_commentaires.py`.

**Détails**
- Visibilité : exactement celle de `detail_document`
  (`ingest/corrections.py`) — même lecture du document (bl ou enlèvement),
  un agent seulement ses dépôts. Un document invisible et une ligne
  invisible donnent tous deux 404.
- `ligne_libelle` = `"<code> — <désignation>"`, ou la partie présente
  seule, ou `"Ligne <ordre + 1>"` si les deux manquent.
- Auteur affiché : `Utilisateur.nom`, sinon `email`.
- Journal : `commentaire_ajoute`, `cible_table="commentaire"`,
  `apres={"document_id": str, "numero": str | None, "ligne": libellé,
  "texte": texte}`.

**Tests (écrits d'abord)**
- ajout puis lecture : le commentaire est sous sa ligne, `nb_commentaires
  == 1`, auteur et date présents ;
- deux commentaires sur la même ligne : du plus ancien au plus récent ;
- texte `"   "` et texte de 1 001 caractères : `CommentaireInvalide` ;
- agent sur le bon d'un autre agent : introuvable (lecture et ajout) ;
  agent sur son propre bon : accepté ;
- identifiant d'une ligne de facture : `LigneIntrouvable` ;
- entrée de journal écrite avec les bonnes clés ;
- relance de la lecture (`enregistrer_extraction_bl` rejouée sur le même
  document) : le commentaire passe dans `sans_ligne` avec son libellé ;
- `corriger_lignes` qui garde la ligne : le commentaire reste dessus ;
- API : 201, 404, 422, 401 sans session.

**Commit** : `ingest/api: commentaires sur les lignes d'un bon`.

## Task C3 : écran et journal

**Fichiers**
- Régénérer `web/openapi.json` et `web/src/api/schema.d.ts`
  (`npm --prefix web run api:schema && npm --prefix web run api:types`).
- Créer `web/src/api/commentaires.ts` (lecture, ajout, clé de cache
  `["document", id, "commentaires"]`).
- Créer `web/src/components/CommentairesLignes.tsx` (spec §6).
- Modifier `web/src/pages/PageBl.tsx` : une seule ligne,
  `<CommentairesLignes documentId={donnees.id} />`, en fin de page.
- Modifier `web/src/lib/journal.ts` : libellé `commentaire_ajoute` →
  « Commentaire ajouté » et mise en forme des clés `ligne` et `texte` ; ne
  jamais afficher `document_id`.

**Vérification**
- typecheck et build verts ;
- vérification visuelle (Playwright, Chromium préinstallé) sur une base de
  test avec des données inventées, à 375 px et à 1 280 px : ajout, liste,
  commentaire sans ligne après relance, message d'erreur ; captures jointes
  au compte rendu, sans donnée réelle.

**Commit** : `web: commentaires sur les lignes depuis la page du bon`.

## Fin de la tâche C

Relecture de l'ensemble de la tâche C (conformité à la spec, puis qualité),
mise à jour de `docs/dette.md` (section datée de la session B : pas de
verrou en base sur les commentaires, pas de compteur dans la liste des
documents) et de la case « Phase 3 : commentaires » de la roadmap §10. Le
lot Prix suit sur la même branche ; la PR vers `dev` est ouverte à la fin de
la phase 3.
