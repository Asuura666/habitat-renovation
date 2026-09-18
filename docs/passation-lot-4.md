# Passation — lot 4 (Rapprochement), 18 septembre 2026

Document de reprise pour la session suivante. **À lire en entier avant de
toucher au code**, avec `CLAUDE.md`, `docs/cahier-des-charges.md` (qui fait
foi), `docs/passation-lot-3.md` (lot précédent), `docs/lot-4-recette.md`
(recette détaillée, commandes exécutées, verdicts réels) et `docs/dette.md`.

---

## 1. État au 18/09/2026

- **Branche `lot-4-rapprochement`** (dépôt `/home/debian/habitat_reno`),
  créée depuis `main` (plan écrit en `bf910d2`), **fusionnée dans `main` le
  18/09/2026** en avance rapide, tête `9151d68`, puis supprimée avec les
  arbres de travail. Aucun remote, rien de déployé.
- **Les 11 tâches techniques (L4-T1 à L4-T11) sont faites et relues.**
  Chaque revue de tâche s'est refermée sans point ouvert, y compris après
  correction quand une revue en avait relevé (détail commit par commit et
  revue par revue dans `docs/lot-4-recette.md` §1). **La revue finale de
  l'ensemble de la branche a eu lieu**, menée en trois périmètres parallèles
  (moteur de règles, orchestration et base, interface) : elle a trouvé un
  défaut critique — la validation d'un bon de livraison pouvait finir en
  erreur alors qu'elle était bien enregistrée — et trois points importants,
  dont l'archivage d'une facture qui laissait ses anomalies ouvertes pour
  toujours. Tous corrigés, re-relus, et détaillés dans
  `docs/lot-4-recette.md` §1.1. Un constat critique annoncé a été écarté
  après vérification (§4).
- **Deux arbres de travail simultanés**, comme au lot 3 : l'arbre principal
  (`/home/debian/habitat_reno`, branche `lot-4-rapprochement`) et un arbre
  séparé (`/home/debian/habitat_reno-wt-l4`, branche `lot-4-pur`, supprimé
  après intégration) pour mener le flux pur (`rules/`, une partie de
  `normalize/`) en parallèle du flux qui touche la base (`ingest`/`api`/
  `web`). Intégration par report de commits (git cherry-pick), deux fois :
  après L4-T1, puis après L4-T5/T6. Correspondance exacte des commits en
  `.superpowers/sdd/plan-lot-4/progress.md`.
- **Journal détaillé** : `.superpowers/sdd/plan-lot-4/` — `progress.md`
  (dispatches, verdicts, décisions), fiches `L4-T*-brief.md`/
  `-controleur.md`, rapports `L4-T*-report.md`, diffs de revue, fichier de
  règles d'exécution commun (`execution.md`), vérification front
  (`verification-front.md`).
- **Environnement de dev** (VPS partagé) : Postgres de dev
  `habitat_reno-postgres-1` (`127.0.0.1:5450`), base `bl`. Base de test
  `bl_test` (arbre principal), `bl_test_wt` (arbre séparé). Le rejeu réel du
  rapprochement sur la facture d'août et les 3 BL (§2 ci-dessous, détail en
  `docs/lot-4-recette.md` §4) a été fait dans une base dédiée et jetable,
  jamais gardée ni commitée.

---

## 2. Ce qui a été fait

Détail commit par commit et revue par revue dans `docs/lot-4-recette.md`
§1. Résumé :

| Tâche | Contenu |
| --- | --- |
| L4-T1 | `rules/modeles.py`, `rules/engine.py` : dataclasses d'entrée, `Anomalie`, `evaluer_facture` ; règles R10 (somme incohérente de la facture) et R11 (idem pour un BL) |
| L4-T2 | R01 (bloc sans BL ni mention), R02 (bloc sans BL, mention « pas de bon »), R12 (doublon de facturation) |
| L4-T3 | R03/R04 (écart de quantité facturée/livrée), R05 (ligne de facture non appariée), R17 (quantité de conditionnement non entière) |
| L4-T4 | R07/R08 (prix hors historique, deux seuils de gravité), R09 (remise habituelle non appliquée) |
| L4-T5 | R13 (avoir sans origine), R06/R14/R15/R16 (règles de suivi qui dépendent du temps écoulé), `evaluer_suivi` |
| L4-T6 | `normalize/unites.py::convertir_en_unite_fact`, `normalize/appariement.py::apparier_lignes` |
| L4-T7 | `ingest/rapprochement.py::rapprocher_facture` : statut par bloc, lignes rapprochées, `qte_fact`, anomalies, déclenché au dépôt d'une facture, après validation d'un BL et après une extraction qui donne un numéro |
| L4-T8 | `ingest/anomalies.py` : génération idempotente (mise à jour, levée), cycle de vie (traiter, ignorer), lecture filtrée |
| L4-T9 | `api/anomalies.py` : `GET /api/anomalies`, `POST /api/anomalies/{id}/traitement` ; `GET /api/a-traiter` gagne les anomalies hautes |
| L4-T10 | `web/src/pages/Anomalies.tsx`, `web/src/lib/regles.ts`, section « Anomalies à traiter » dans l'écran « À traiter » |
| L4-T11 | `ingest/suivi.py::controles_differes`, commandes CLI `rapprocher`/`controles-differes`, `docs/exploitation-lot-4.md` |
| L4-T12 | Cette passation, `docs/lot-4-recette.md`, `docs/dette.md` et `CLAUDE.md` mis à jour |

**Verdicts réels sur la facture d'août** (contrôleur, rejeu complet du
rapprochement, aucune valeur client) : 28 blocs (3 reçus, 4 « pas de bon »,
21 non reçus), 25 anomalies (R01 ×21, R02 ×4, R13 ×3), `qte_fact` renseignée
sur 113 des 136 lignes de facture, 3 lignes appariées à une ligne de BL,
aucun écart de quantité signalé à tort, aucune anomalie de prix (un seul
mois d'historique). **Non confirmé par Ilane** (Q6). Détail en
`docs/lot-4-recette.md` §4.

---

## 3. Décisions

### 3.1 Validées par Ilane (17/09/2026, avant le début du lot)

- « Le lot 4 toute la nuit » (mandat d'exécution en autonomie, sans
  validation préalable) — chaque décision prise sans elle est listée avec
  son coût si elle est mauvaise (`docs/plan-lot-4.md` §4, reproduit dans
  `docs/lot-4-recette.md` §2.1).
- « Quand tu as fini le lot 4 tu fais le merge en main puis tu enchaînes
  avec le lot 5 » — autorisation durable : fusionner `lot-4-rapprochement`
  dans `main` dès que la revue finale de branche est verte et la suite
  complète au vert, puis démarrer le plan du lot 5 (Restitution) sans
  attendre de nouvelle validation. **Fusion faite le 18/09/2026** (avance
  rapide, aucun conflit), suite complète rejouée verte sur le résultat
  fusionné, branche et arbres de travail supprimés. La suite immédiate est
  donc le lot 5 (§7).
- Mode de travail inchangé depuis les lots précédents : autonomie,
  sous-agents Sonnet uniquement, enchaîner les lots.

### 3.2 Prises en préparant le lot — décisions de conception (L4-D1 à L4-D18)

Liste complète, avec pourquoi/coût si faux et question associée quand il y
en a une, dans `docs/plan-lot-4.md` §4 et reproduite dans
`docs/lot-4-recette.md` §2.1. **À valider par Ilane** (questions Q1 à Q6,
non bloquantes, décisions provisoires déjà en place) :

- **Q1 / L4-D16** — semi-remorque : aucune anomalie construite, faute d'un
  déclencheur défini avec le client (le CDC dit lui-même que ce point sera
  précisé à partir de cas réels).
- **Q2 / L4-D9** — historique de prix : médiane sur 6 mois, aucune anomalie
  sous 3 occurrences ; avec un seul mois réel, ce seuil n'a jamais pu être
  exercé sur des données réelles.
- **Q3 / L4-D17** — écran Anomalies réservé à l'admin, l'agent ne le voit
  pas.
- **Q4 / L4-D12** — une anomalie ouverte dont la cause disparaît est
  supprimée (pas conservée sous un autre statut), sa levée journalisée.
- **Q5 / L4-D5 (avoirs)** — les 3 lignes négatives de la facture d'août
  traitées comme des avoirs de ligne (R13) ; un document d'avoir complet
  reste non géré (dette héritée du lot 2).
- **Q6** — les 28 verdicts reçu/non reçu/pas de bon de la facture d'août
  (§2) ne peuvent pas être confirmés sans Ilane : seule la correspondance
  entre 3 des 4 photos disponibles et cette facture est sûre.

### 3.3 Prises en cours d'exécution

Liste complète dans `docs/lot-4-recette.md` §2.2. En résumé (aucune n'a de
conséquence irréversible, rien n'est déployé) :

- **R1, R6** : ordre d'exécution des tâches, sans effet sur le comportement
  livré.
- **R2, R3** : précisions sur l'arrêt du moteur de règles quand un document
  est incohérent, et sur ce qui rend un bloc « reçu ».
- **R4** : organisation en deux arbres de travail, intégration par report de
  commits.
- **R5** : repli d'affichage du chantier dans le détail d'une anomalie de
  bloc.
- **R8** : la suppression des anomalies obsolètes exige désormais toujours
  l'ensemble complet des règles recalculées.
- **R9** : portée de R17 confirmée sur la ligne de facture.
- **R10, R14, R16** : trois décisions liées à la conversion des quantités —
  une unité non imprimée est acceptée côté facture (R10), puis étendue au
  cas où aucune unité n'est connue des deux côtés (R14, découvert en
  rejouant le rapprochement sur la facture réelle : Unikalo n'imprime aucune
  unité), puis restreinte pour ne jamais comparer une quantité ainsi rendue
  telle quelle à une quantité réellement convertie (R16, un point de dette
  assumé en résulte).
- **R11** : les règles de prix ignorent l'état du BL.
- **R12** : les ensembles de règles deviennent une constante partagée.
- **R13** : une anomalie porte, quand c'est pertinent, l'identifiant du
  chantier ou de l'alias concerné, pour ne jamais confondre deux chantiers
  ou deux alias distincts.
- **R15** : l'API accepte une valeur de statut qui retire le filtre par
  défaut (nécessaire pour l'écran, qui doit montrer l'historique complet).
- **R17** : toute anomalie de facture porte désormais l'identifiant de sa
  facture (un point de dette de déploiement en résulte, sans effet tant que
  rien n'est en production).
- **R18** : présentation française des quantités (virgule, pas de point).
- **R19** : la résolution du chantier d'une anomalie, en lecture, regarde
  d'abord l'anomalie elle-même.

---

## 4. Questions ouvertes (non bloquantes, décisions provisoires en place)

Q1 à Q6 ci-dessus (§3.2). Plus, héritées des lots précédents, toujours
ouvertes :

- **30 photos de BL réelles dont 10 dégradées**, avec leurs valeurs
  attendues (bloque la mesure du critère CDC §10, hérité du lot 3).
- **Factures et bons d'enlèvement Point.P** (bloque le parseur Point.P et
  tout rapprochement avec ce fournisseur).
- **Format d'un avoir Unikalo** (hérité du lot 2, toujours sans exemple).
- **Identifiants des deux groupes Telegram et vrai bot** (hérité du lot 2,
  bloquant pour tout test Telegram réel).
- **Accès Google Drive** (dossier cible et compte autorisé) — nécessaire
  pour la synchronisation prévue au lot 5.

---

## 5. Méthode qui a fonctionné (reconduite depuis les lots précédents)

Inchangée dans ses grandes lignes par rapport à `docs/passation-lot-3.md`
§5 : un plan par lot (`docs/plan-lot-4.md`), exécution en tâches avec un
agent qui implémente, un agent qui relit, un tour de correction sur les
points Important, une re-revue, les points mineurs consignés plutôt que
traités dans l'instant, un journal (`progress.md`), un fichier de règles
d'exécution commun. Particularités de ce lot-ci :

- **Deux arbres de travail simultanés** presque en permanence, comme au lot
  3 (§1). Le flux pur (`rules/`, une partie de `normalize/`) a tourné dans
  l'arbre séparé pendant que l'arbre principal avançait sur `ingest`/`api`/
  `web`, intégré ensuite par report de commits.
- **Mesure réelle en cours de lot, deux fois** : après une première version
  du rapprochement (L4-T7), le contrôleur a rejoué le calcul sur la facture
  d'août et les 3 BL disponibles et a découvert que la quantité convertie
  restait vide sur toutes les lignes (Unikalo n'imprime aucune unité nulle
  part) — corrigé en cours de tâche (décision R14). Une seconde mesure,
  après cette correction et la suivante, a produit les chiffres définitifs
  repris en §2 et dans `docs/lot-4-recette.md` §4.
- **Deux tâches (L4-T7, L4-T9) ont nécessité plus d'un tour de correction**,
  chacune refermée avant de passer à la suite.

---

## 6. Pièges rencontrés (à éviter)

En plus de ceux déjà listés dans `docs/passation-lot-3.md` §6 (toujours
valables) :

- **Un agent interrompu peut redémarrer pendant qu'un autre reprend son
  travail dans le même arbre.** Rencontré deux fois ce lot-ci (L4-T7, une
  fois par tour de correction) : l'agent d'origine, épuisé, s'est réveillé
  pendant qu'un agent neuf travaillait déjà à sa place. Les deux fois,
  l'agent redémarré a été arrêté aussitôt et l'état du dépôt vérifié avant
  de continuer. Toujours vérifier qu'un agent interrompu ne va pas
  reprendre la main avant de confier son travail à un agent neuf.
- **Le rapport final d'un agent interrompu peut décrire un état faux.** Un
  agent interrompu par le harnais a rendu un rapport annonçant un travail
  terminé et commité qui, en réalité, avait échoué sur un hook de
  formatage et n'était pas commité, et une décision qu'il disait avoir
  appliquée n'existait nulle part dans le code. Toujours vérifier l'état
  réel du dépôt (`git log`, `git status`, `git diff`) avant de croire le
  rapport d'un agent qui a été interrompu, plutôt que de repartir de ce
  rapport.
- **Deux processus `pytest` sur la même base de test produisent des échecs
  qui n'ont rien à voir avec le code.** Un run complet lancé en même temps
  que deux runs partiels sur la même base a produit plusieurs échecs de
  verrouillage PostgreSQL, sans lien avec la tâche en cours — reconnus comme
  un artefact d'exécution concurrente, pas une régression, une fois les
  runs redondants arrêtés et la suite rejouée seule. Un seul processus
  `pytest` à la fois par base de test, sans exception.
- **Modifier un fichier pendant qu'un `git commit` (avec un hook qui relance
  toute la suite de tests) est en cours peut faire échouer le hook** avec
  une erreur du type « files were modified by this hook », sans perdre de
  commit (rien n'est créé, `git log` le confirme) mais en faisant échouer
  la tentative. Ne jamais toucher un fichier pendant qu'un commit est en
  cours d'exécution.
- **Une date ISO 8601 avec un fuseau explicite (`+00:00`) mal encodée dans
  une chaîne de requête devient un espace.** Un filtre d'API qui accepte
  des dates avec fuseau doit encoder la chaîne de requête (`urllib.parse
  .quote` côté test, encodage standard côté navigateur) plutôt que de
  l'interpoler brute — sinon le `+` est interprété comme un espace et la
  date devient invalide.

---

## 7. Point de départ du lot 5 — Restitution (CDC §11)

**Prérequis avant de commencer** :
1. Fusionner `lot-4-rapprochement` dans `main` (mandat déjà donné, §3.1) —
   la revue finale de la branche complète est faite et ses corrections
   intégrées (§1) ; vérifier la suite complète sur le résultat fusionné
   avant de supprimer la branche.
2. Relire `docs/dette.md` (sections des lots 3 et 4 en particulier) et les
   questions ouvertes (§4 ci-dessus) — en particulier l'accès Google Drive,
   nécessaire dès que la synchronisation est abordée.

**Contenu du lot 5** (CDC §11, tel que résumé par le contrôleur en cours de
lot 4) :
- Écrans Chantiers & fournisseurs et Bilan, avec navigation chantier →
  fournisseur → BL → document et une version mobile en cartes ;
- export CSV ;
- synchronisation Google Drive ;
- écran de journal (traçabilité) ;
- paramétrage des seuils (`parametre`, créés avec leur valeur par défaut au
  lot 4, L4-D10 — aucun écran ne permet encore de les modifier).

**Point de départ dans le code** :
- `bloc_facture.bl_document_id`/`statut_rapprochement` sont désormais
  persistés (L4-D4) : la navigation chantier → fournisseur → BL peut s'
  appuyer dessus sans recalcul.
- `GET /api/anomalies` (L4-T9) et l'écran Anomalies existent déjà : le
  Bilan peut les réutiliser plutôt que de dupliquer une requête.
- `ingest/suivi.py::controles_differes` et la commande CLI existent, mais
  **la ligne cron quotidienne documentée dans `docs/exploitation-lot-4.md`
  n'est pas encore posée sur le VPS client** — à faire lors du déploiement
  du lot 5 (ou avant, si le lot 4 est mis en production seul).
- `parametre` est en base avec ses 9 clés et leurs valeurs par défaut
  (L4-D10) : le paramétrage du lot 5 doit lire/écrire ces mêmes clés, pas en
  créer de nouvelles sans raison.
- `docs/dette.md` à reprendre : parseur Point.P toujours non construit
  (bloque tout rapprochement avec ce fournisseur), avoir complet toujours
  non géré, comparaison de quantité perdue dans les cas mixtes (L4-T7 tour
  2), remarque de déploiement sur l'identité d'une anomalie (L4-T7 tour 2)
  — sans objet tant que rien n'est en production, mais à traiter avant la
  première mise en service si des anomalies s'étaient accumulées entre
  temps.

**Questions à poser à Ilane avant ou pendant le lot 5** : Q1 à Q6 de ce
lot-ci (§3.2, en particulier Q6 — confirmer les verdicts de la facture
d'août avant de les présenter dans un Bilan) ; l'accès Google Drive (§4) ;
les questions héritées des lots 2 et 3 (30 photos, Point.P, format d'un
avoir, groupes/bot Telegram réels).
