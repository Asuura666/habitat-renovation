# Mise en production du 1er octobre — recette (27/09/2026)

Branche `feature/mise-en-prod-1-octobre`, partie de `dev` après le socle
commun (PR #1). Spec :
`docs/superpowers/specs/2026-09-27-mise-en-production-1er-octobre-design.md` ;
plan : `docs/superpowers/plans/2026-09-27-mise-en-production-1er-octobre.md` ;
organisation d'ensemble : `docs/roadmap-octobre-2026.md`.

## 1. Ce qui est livré

| # | Tâche | Commits |
| --- | --- | --- |
| 1 | Migration 0011 (légende, chantier à compléter, fusion), seuil de ressemblance (90 %) | socle commun (PR #1) |
| 2 | Ressemblance (0-100, sans casse/accents/ponctuation/ordre des mots) et table de décision | socle commun |
| 3 | Règle R18 « Chantier à confirmer » | socle commun |
| 4 | Légende de la photo Telegram lue, conservée, affichée | `830928d` |
| 5 | Rattachement automatique des bons et des factures (création « à compléter », apprentissage du nom lu, alerte, verrou) | `6c095bc` |
| 6 | « À régler » : nouveaux chantiers à compléter, choix du chantier sur l'alerte (création possible), changer le chantier d'un bon | `c8f53bb`, `eb986d5` |
| 7 | Fusion de deux chantiers | `279644d` |
| 8 | Reprise des noms en attente (`rattacher-chantiers`) | `d13ee2c` |
| 9 | Photos rangées `bl/<année>/<mois>/<jour>_<déposant>_<chantier>_n<numéro>` (liens physiques) + `ranger-photos` | `8681c0b` |
| 10 | Comptes, serveur (créer, modifier, mot de passe, retirer/rétablir l'accès, garde-fous, sessions coupées) | `d8121d1`, `cbd842f` |
| 11 | Comptes, écran | `3ed36a4`, `8cb1315` |
| 12 | Journal : noms au lieu des identifiants, toutes les actions en français | `dd211d9` |
| 13 | Fiche fournisseur par mois, « Conforme » cliquable → livraisons | `0305c35` |
| — | Corrections de la relecture finale | `3f18901`, `53c0290`, `45a13b7` |

## 2. Décisions prises en cours de route (à relire par Ilane)

1. Reprise : un chantier créé depuis un nom en attente prend le libellé brut le plus récent lu sur un bon ou une facture (« VILLA TEST »), pas la forme normalisée (« villa test »).
2. Toutes les nouvelles actions du journal ont un libellé français.
3. `ressemblance` est générique (`normalize/texte.py`), réutilisée par la phase 3 pour les produits.
4. La session fusionne elle-même ses PR dans `dev` si tout est vert (confirmé par Ilane).
5. Relectures en lecture seule menées en parallèle de la tâche suivante quand elle ne dépend pas du code relu ; jamais deux agents qui écrivent en même temps.
6. Quand le chantier d'un bon change par propagation d'un nom appris, sa photo est renommée par `ranger-photos` (déploiement, puis chaque nuit en phase 2), pas sur le moment.
7. La reprise ne range pas les photos elle-même : `ranger-photos` passe juste après au déploiement.
8. Verrou consultatif sur la garde « dernier administrateur ».
9. `agence` reste facultative sur un compte (dirigeants multi-agences).
10. Journal : un identifiant introuvable s'affiche « (inconnu) », pas « (supprimé) » (rien n'est supprimé physiquement).
11. Relectures confiées à Sonnet (consigne d'Ilane : Opus seulement en escalade), la relecture finale découpée en trois angles.
12. Unicité de l'identifiant Telegram garantie par le verrou des comptes (pas de nouvelle migration : les numéros 0012+ sont réservés à la phase 3).
13. Un bon dont l'alerte « Chantier à confirmer » a été réglée par un humain garde ce choix si une correction le fait retomber en alerte (une anomalie ne se rouvre jamais).
14. La création et la modification manuelles d'un chantier passent sous le même verrou que la création automatique.
15. (audit B-05, 29/09/2026, décision d'Ilane) Deux noms qui ne diffèrent que par un ou plusieurs nombres (« Lot 12 » / « Lot 13 ») ne sont **jamais** rattachés automatiquement, quelle que soit la ressemblance : le chantier voisin est seulement proposé (R18 « Chantier à confirmer » sur un bon, alias en attente sur une facture), sans alias appris. Une légende voisine numérotée ne confirme pas non plus le chantier du nom lu. Les alias déjà appris ne sont pas modifiés : `python -m app.cli chantiers-alias-suspects` les liste (lecture seule).

## 3. Relectures

- Chaque tâche : relecture conformité + qualité par un agent distinct ; défauts réels trouvés et corrigés : création d'un chantier depuis l'alerte (T6), bons archivés comptés (T6), course sur le dernier administrateur (T10), formulaire de compte non lié au compte affiché et identifiant Telegram non vérifié (T11).
- Relecture finale en trois angles (chantiers et données ; sécurité, comptes, API ; écran et textes) :
  - critique : un bon réglé par un humain perdait son chantier si une correction le faisait retomber en alerte → décision humaine conservée ;
  - importants : création manuelle de chantier hors verrou, identifiant Telegram en double possible sous concurrence, « À régler » pas rafraîchi après avoir complété un chantier, fusion sans confirmation avec une cible présélectionnée ;
  - mineurs corrigés : boutons de la fiche chantier sur téléphone, message « introuvable » sur une erreur réseau, « Agent » → « Employé », filtre `?etat=` inconnu.
- Autorisations : toutes les nouvelles routes sont réservées aux administrateurs (vérifié route par route, tests 403).

## 4. Déploiement (après fusion `dev` → `main`, accord d'Ilane)

Pour chaque instance (démo puis production), procédure de `memory.md` §6 :

1. Dump de la base dans `~/sauvegardes-habitat/avant-1er-octobre-<instance>-<date>.dump`.
2. `build api`, `stop api`, `run --rm api alembic upgrade head` (révision `0011`), `up -d --wait`.
3. **Dans cet ordre** : `python -m app.cli rattacher-chantiers` puis `python -m app.cli ranger-photos`. La reprise tient le verrou des chantiers pendant toute sa durée : quasi instantanée aujourd'hui (aucun chantier en production), à ne pas relancer sur un gros arriéré aux heures de dépôt.
4. Vérifier `/health`, le webhook Telegram, l'écran (À régler, Chantiers, Comptes, Journal, Livraisons).
5. Production : **changer tout de suite le mot de passe admin** depuis l'écran Comptes (il a été exposé dans une sortie d'outil le 23/09), puis créer les comptes des employés avec leur identifiant Telegram.

## 5. Reporté (détail dans `docs/dette.md`)

Voir la section « Mise en production du 1er octobre (27/09/2026) — reporté » de `docs/dette.md`.
