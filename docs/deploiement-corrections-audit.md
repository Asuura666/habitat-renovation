# Déploiement des corrections d'audit (branche `feature/corrections-audit`)

Page courte, propre à cette livraison. Elle complète
`docs/deploiement-octobre-2026.md` (variables `I`, `P`, `PORT` du §4) et
`docs/deploiement-et-tests.md` (procédure générale). **Exécutée le 30/09/2026** : démo à 07:29 UTC, production à 07:31 UTC (étiquette `mise-en-prod-2026-09-30`) ; `rapprocher --tout` sans échec et aucun alias suspect sur les deux instances.

## Ce qui change

- Aucune **migration** dans cette livraison. La migration `0015` (colonne
  `prix_internet.offres`) vient de la livraison précédente : si elle n'est pas
  encore appliquée sur l'instance, `alembic upgrade head` l'applique au
  passage, sinon il ne fait rien (`alembic current` doit afficher `0015`).
- Nouveau calcul serveur : regroupement des lignes d'un même code, verdict
  « Conforme » unique, mention « dont X € » dans « À régler », page du bon.

## Ordre

Toutes les commandes depuis le dossier de l'instance, avec `I`, `P` et `PORT`
définis comme au §4 de `docs/deploiement-octobre-2026.md`.

1. **Sauvegarde (dump)**, sans continuer si elle échoue :

   ```bash
   (umask 077; docker compose $P exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
     > /home/debian/sauvegardes-habitat/avant-corrections-audit-${I}-$(date +%Y%m%d-%H%M).dump)
   ls -la /home/debian/sauvegardes-habitat/avant-corrections-audit-${I}-*.dump   # taille non nulle
   docker tag habitat_${I}-api:latest habitat_${I}-api:avant-corrections-audit   # retour arrière du code
   ```

2. **Construire et redémarrer l'API** (pas de migration à lancer à la main) :

   ```bash
   docker compose $P build api
   docker compose $P up -d --wait api
   curl -fsS http://127.0.0.1:${PORT}/health
   ```

3. **Rejouer le rapprochement** de toutes les factures, puis attendre la
   synthèse « N factures traitées, **0 échec** » (sinon s'arrêter et lire les
   lignes en échec) :

   ```bash
   docker compose $P exec -T api python -m app.cli rapprocher --tout
   ```

4. **Alias de chantier suspects** (lecture seule, rien n'est modifié ; la
   sortie contient des noms de chantier : ne pas la planifier ni la copier
   ailleurs). À relire par Ilane :

   ```bash
   docker compose $P exec -T api python -m app.cli chantiers-alias-suspects
   ```

5. **Contrôles visuels** dans le navigateur :
   - « À régler » : le nombre annoncé et la mention « dont X € » ;
   - une page de bon à plusieurs lignes du même code : le livré du groupe
     (« 20 (10 + 10) ») face au facturé, la ligne suivante « Incluse dans la
     ligne précédente » ;
   - une page de bon « À vérifier » sans problème : la pastille dit pourquoi
     (« bon à valider » ou « facture à vérifier »).

## Retour arrière

- Code : remettre l'image d'avant et redémarrer.

  ```bash
  docker tag habitat_${I}-api:avant-corrections-audit habitat_${I}-api:latest
  docker compose $P up -d --wait api
  ```

- Données : cette livraison ne change pas le schéma ; le rapprochement rejoué
  ne fait qu'ouvrir ou fermer des anomalies. Si elles sont à remettre telles
  qu'avant, restaurer le dump de l'étape 1 avec `deploy/restore.sh` (voir
  `docs/deploiement-et-tests.md` §11) ; `restore.sh` arrête l'API pendant sa
  copie de sécurité et, s'il s'arrête à cette phase, affiche la commande exacte
  pour la relancer.
