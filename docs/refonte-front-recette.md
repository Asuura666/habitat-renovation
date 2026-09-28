# Recette de la refonte du front — Contrôle BL & factures

Branche `refonte-front`, créée depuis `main` à `83a8bd4`, 48 commits jusqu'à
`f1404bc`, le tout le 23/09/2026 (08h12–22h10). Objectif : remplacer les 14
écrans techniques par une interface « Registre » lisible par un dirigeant non
technique, sur ordinateur et sur téléphone, pour la démo du samedi 26/09/2026.
Spec : `docs/superpowers/specs/2026-09-23-refonte-front-design.md` (maquettes
`Main`, `ARegler`, `FicheChantier`, `BL`). Plan :
`docs/superpowers/plans/2026-09-23-refonte-front.md`.

Aucune donnée client n'est reproduite ici : ni montant, ni nom, ni numéro
réel de client, de chantier ou de document. Les chiffres cités pour la
démo (comptes de problèmes, montants) proviennent de la base de
démonstration, entièrement fictive.

## À lire d'abord (Ilane)

- **Livré et fusionné dans `main`** : cinq écrans (Vue d'ensemble, À régler,
  Chantiers, Fournisseurs, Documents) plus la page BL, Réglages et Journal à
  la nouvelle charte, navigation téléphone à barre basse, plus aucun jargon
  technique visible (code de règle, « bloc », « alias », « rapprochement »).
  Détail écran par écran en §1.
- **Déployé le 23/09/2026 sur les deux instances** : démo
  (https://demo.habitat.ellumena.fr) et production
  (https://habitat.ellumena.fr), migration `0010` appliquée, les deux
  reparties saines. Détail en §5.
- **Construit et relu en une journée**, par tâche puis par une revue finale
  à 6 angles sur l'ensemble de la branche : 85 constats bruts, 19 confirmés
  après vérification contradictoire, tous corrigés et revérifiés avec
  captures d'écran avant la fusion. Détail en §2.
- **Quatre ajouts serveur seulement** (§1.4) : le reste est de la
  présentation. Aucune règle métier n'a été ajoutée ni modifiée ; le moteur
  de règles R01–R17 et le rapprochement du lot 4 sont inchangés.
- **Rien n'est validé par un utilisateur réel.** Les vérifications visuelles
  utilisent une base de démonstration fictive ; une recette d'usage par
  Ilane elle-même reste à faire, de préférence avant la démo du 26/09.
- **Des écarts à la spec de conception restent à valider** (§3) : un sixième
  état de chantier (`a_voir`), le titre d'une règle reformulé, et le
  principe de deux comptes distincts de « problèmes » (le mois affiché,
  et le total « à régler »).
- **Points ouverts à traiter avant d'aller plus loin** : accès Google Drive,
  rotation des secrets collés pendant la session, sauvegardes et crons à
  poser sur les deux instances déployées. Liste complète en §6.

## 1. Ce qui a été livré, écran par écran

### 1.1 Navigation

Cinq entrées dans une barre latérale (ordinateur) ou une barre basse fixe à
5 icônes (téléphone, sous 768 px) : **Vue d'ensemble**, **À régler**,
**Chantiers**, **Fournisseurs**, **Documents** ; deux liens discrets en bas
de barre latérale : **Réglages**, **Journal**. Un agent de terrain ne voit
que « Documents » et la déconnexion — toute autre route admin le renvoie
silencieusement vers `/documents`. Les anciennes URL (`/bilan`, `/factures`,
`/anomalies`, `/bl`…) redirigent vers les nouvelles ou restent montées le
temps qu'un écran équivalent existe ; aucun lien envoyé par Telegram n'est
cassé. Sur téléphone, chaque écran se présente en cartes empilées plutôt
qu'en tableau, et le détail d'un problème (« À régler ») s'ouvre en page
plein écran plutôt qu'en panneau latéral.

### 1.2 Les cinq écrans

- **Vue d'ensemble** (`/`) — sélecteur de mois, six chiffres du mois
  (Facturé, Conforme, Écart prix/quantité, Sans bon de livraison, Problèmes
  à régler dont urgents, BL reçus/facturés), tableau des chantiers trié par
  montant à vérifier avec une pastille d'état par chantier, et les quatre
  problèmes les plus prioritaires. Export Excel du détail du mois.
- **À régler** (`/a-regler`, `/a-regler/:id`) — liste unique de tout ce qui
  attend une décision : anomalies ouvertes, documents à corriger, chantiers
  à rattacher, en langage courant et filtrable (Tous, Urgents, BL manquants,
  Prix, Quantités, À rattacher, Bons illisibles, Déjà réglés). Le détail
  d'un problème affiche « Pourquoi c'est signalé » avec les valeurs
  chiffrées, des liens vers la facture et le bon, un commentaire obligatoire
  et deux actions (« Contesté auprès du fournisseur », « C'est normal,
  ignorer »).
- **Chantiers** (`/chantiers`, `/chantiers/:id`) — liste avec création de
  chantier et filtre agence ; fiche chantier avec client, agence, dernier
  bon retrouvé, quatre chiffres, la liste de toutes les livraisons (clic
  vers la page BL) avec leurs problèmes propres, et l'édition
  nom/client/agence/actif.
- **Fournisseurs** (`/fournisseurs`, `/fournisseurs/:id`) — liste avec les
  mêmes quatre chiffres et le nombre de problèmes ; fiche avec les chantiers
  concernés et les problèmes ouverts.
- **Documents** (`/documents`, `/documents/:id`, `/bl/:id`) — liste
  filtrable (factures / bons de livraison / mois / chantier / fournisseur /
  à corriger), dépôt d'une facture PDF ; **page BL** dédiée avec la photo,
  le téléchargement nommé, le tableau livré/facturé/prix/contrôle par
  ligne (calculé côté serveur), et la correction de lecture existante. Un
  agent n'y voit que ses propres dépôts, comme avant.
- **Réglages** et **Journal** — même contenu qu'avant (neuf seuils
  modifiables, journal des écritures), nouvel habillage et libellés en
  français courant.

### 1.3 Langage courant

Un seul module (`web/src/ui/libelles.ts`) traduit chaque code de règle
(R01–R17) en titre lisible (ex. R01 → « Bon de livraison jamais reçu ») et
chaque gravité en « Urgent » / « À voir » / « Info ». Aucun code de règle,
« bloc », « alias » ni « rapprochement » n'apparaît à l'écran. Une règle
inconnue ou un `detail` incomplet se replie sur un libellé générique plutôt
que de casser l'écran.

### 1.4 Ajouts serveur (les seuls, règles de frontière inchangées)

1. **Client du chantier** — colonne `chantier.client` (migration `0010`),
   lecture/écriture par `POST`/`PUT /api/chantiers/{id}` (nouvelle route de
   modification). Hors cahier des charges, ajout demandé par Ilane le
   23/09/2026 ; texte libre, sans référentiel dédié.
2. **Tableau de bord du mois** — `GET /api/tableau-de-bord?mois=` :
   totaux du mois, problèmes ouverts/urgents, BL reçus/facturés, état
   calculé par chantier (`conforme`, `bl_manquant`, `prix`, `quantites`,
   `a_rattacher`, et un sixième état `a_voir`, voir §3), problèmes
   prioritaires. Réutilise les agrégats existants du Bilan (lot 5), jamais
   un second calcul divergent.
3. **Téléchargement nommé et comparaison d'un bon** —
   `GET /api/documents/{id}/fichier?telechargement=true` renvoie un nom de
   fichier explicite (`BL_<numéro>_<chantier>.jpg`) ; nouvelle
   `GET /api/documents/{id}/comparaison` fournit, pour un BL, ses lignes
   avec la quantité et le prix facturés appariés et le contrôle par ligne.
4. **Compte unique des problèmes à régler et catégorisation unique** —
   `GET /api/a-regler/compte` (ajouté à la correction finale, §2) donne le
   même nombre que la liste « À régler » et alimente à la fois la pastille
   de navigation, l'en-tête de l'écran et le total « en tout » de la vue
   d'ensemble ; une table serveur unique (`CATEGORIES_REGLE`) remplace trois
   classifications qui avaient dérivé entre le Bilan, le tableau de bord et
   le front pendant la construction.

Chaque ajout a ses tests service et route (admin/agent) et ses types
`openapi-typescript` régénérés.

## 2. Comment ça a été construit et relu

Dix tâches techniques (1 à 10), implémentées puis relues indépendamment,
jusqu'à trois implémenteurs en parallèle (chacun dans son propre arbre de
travail et sa propre base de test) pour tenir le délai. Chaque tâche a été
fusionnée seulement après une revue verte :

| Tâche | Contenu | Tours de correction |
| --- | --- | --- |
| T1 | Client du chantier, `PUT /api/chantiers/{id}` | revue directement verte |
| T2 | Tableau de bord du mois | 1 tour |
| T3 | Téléchargement nommé, comparaison d'un BL | revue directement verte |
| T4 | Socle web (charte, composants, navigation, routes) | 1 tour |
| T5 | Vue d'ensemble | 1 tour |
| T6 | À régler | 3 tours (dont 1 constat critique : plantage sur une date absente) |
| T7 | Chantiers et fiche chantier | 4 tours |
| T8 | Page BL et Documents | 3 tours |
| T9 | Fournisseurs | 2 tours |
| T10 | Réglages et Journal à la charte | 3 tours |

Chaque tour de correction a été relu à nouveau avant d'être considéré clos ;
le détail (constats, corrections, minorités reportées) est dans le registre
interne de la tâche, non reproduit ici — les points restés ouverts sont
résumés en §6.

**Revue finale de l'ensemble de la branche.** Une fois les dix tâches
fusionnées, un relecteur indépendant a examiné tout `main..HEAD` selon six
angles (liens entre écrans, cohérence serveur, droits agent/admin, fidélité
aux maquettes, présentation téléphone, couverture de la spec) : 85 constats
bruts, dont 28 classés Critique/Important. Ces 28 ont ensuite été vérifiés
un par un par deux relecteurs contradictoires (« sceptiques ») cherchant à
réfuter chaque constat : **19 confirmés**, 9 rétrogradés en mineur (le code
réglait déjà le problème ou le constat était inexact), aucun rejeté sans
explication. Les 57 constats mineurs restants ont été triés : la plupart
corrigés dans la foulée, le reste consigné dans `docs/dette.md` (résumé en
§6).

Les 19 constats confirmés ont tous été corrigés (huit commits, dont quatre
par un premier correcteur interrompu par une limite de session puis repris
intégralement par un second) et **revérifiés un par un** : preuve de code
(fichier/ligne), test dédié, et captures d'écran ou vérification en direct
sur une copie jetable de la base de démonstration (clic réel sur un
problème, traitement, retour à l'écran d'origine, lecture des chiffres
avant/après). Exemple : trois compteurs de « problèmes » différents sur le
même parcours de démo (tuile du mois, pastille de navigation, en-tête d'« À
régler ») ont été unifiés autour d'un compte serveur unique et de libellés
qui disent chacun leur périmètre (« ce mois » / « en tout »).

Après cette vague, deux nouveaux défauts mineurs sont apparus à l'écran
pendant la vérification de la démo (position de défilement au retour sur
« À régler », couleur de la pastille) : jugés visibles sur l'écran vedette
de la démo, ils ont été corrigés avant la fusion plutôt que reportés, avec
une seconde vérification chiffrée du comportement de défilement et un test
qui vérifie la règle exacte (dernier commit, `f1404bc`).

## 3. Décisions et écarts à valider par Ilane

| # | Décision ou écart | Coût si l'hypothèse est fausse |
| --- | --- | --- |
| 1 | Sixième état de chantier `a_voir` (anomalie ouverte sans écart de prix/quantité ni BL manquant, ex. un avoir seul) en plus des cinq états de la spec §6.2 ; titre de R16 devenu « Chantier sans bon déposé récemment » (le délai est un réglage, plus « depuis 7 jours » en dur). | Spec non modifiée, à faire valider ; sinon un libellé ou un état à ajuster, sans migration de données. |
| 2 | Deux comptes distincts de « problèmes », chacun désormais nommé et cohérent en lui-même : la tuile de la vue d'ensemble compte les anomalies du mois choisi (périmètre du Bilan) ; la pastille de navigation et l'écran « À régler » comptent tout ce qui attend une décision, tous mois confondus, documents et chantiers à rattacher compris. | Si un seul chiffre est attendu partout, il faut fusionner les deux périmètres — un endpoint à revoir, sans perte de données. |
| 3 | Sur téléphone, chaque changement d'écran remonte en haut, sauf entre la liste et le détail d'« À régler » sur un écran ≥ 1024 px (panneau maître/détail) : règle unique, la plus simple qui couvre la démo. | Au retour à la liste « À régler » depuis un problème sur téléphone, l'écran repart en haut plutôt qu'à la position quittée — accepté pour la démo. |
| 4 | Construction en parallèle : jusqu'à trois implémenteurs simultanés, chacun dans un arbre de travail et une base de test isolés, fusion séquentielle et résolution des conflits par un seul contrôleur — seul moyen de tenir le délai du 26/09. | Conflits de fusion sur les routes et les types générés ; tous résolus pendant la construction, aucun laissé ouvert. |

Aucune de ces décisions n'est irréversible ; toutes se corrigent sans
migration de données autre qu'un ajustement de code et de tests.

**Addendum du 24/09/2026 — décision (déjà prise, pas à valider) : contrôles
de prix désactivés.** Un seul mois de factures ne fonde aucun « prix
habituel » ; R07/R08/R09 sont désactivées côté serveur
(`CONTROLE_PRIX_ACTIF`, optionnelle, défaut `false`,
`ingest.commun.regles_desactivees`) et leurs anomalies existantes sont
masquées de tous les écrans (jamais fermées ni supprimées — voir
`docs/dette.md`). Deux adaptations front, sans nouveau calcul : la tuile
« Écart prix ou quantité » devient « Écart de quantité », le filtre « Prix »
de l'écran « À régler » disparaît ; l'écran Réglages signale les trois
seuils concernés comme sans effet pour l'instant. Réactivation : variable
dans le fichier d'environnement de l'instance (`.env.prod` / `.env.demo`)
puis recréation du conteneur API (`up -d api`), voir
`docs/evolutions-proposees.md` §b, quand l'historique couvre plusieurs
mois, sans interrupteur à l'écran.

**Second addendum du 24/09/2026 — décision (déjà prise, pas à valider) : R06
« Livré mais pas facturé » désactivée.** Même jour, seconde décision
d'Ilane : aucune preuve encore constatée que ce cas se produise. Même
mécanisme que ci-dessus (`CONTROLE_LIVRE_NON_FACTURE_ACTIF`, optionnelle,
défaut `false`, même fonction `ingest.commun.regles_desactivees`), mais R06
est une règle de **suivi** (contrôle différé, `ingest.suivi
.controles_differes`, commande `controles-differes`) : désactivée, elle
n'est plus évaluée du tout, plutôt que seulement masquée après coup. Ses
anomalies existantes restent masquées de tous les écrans, pas touchées par
un passage des contrôles différés tant que R06 reste désactivée (voir
`docs/dette.md`, qui signale aussi une lacune préexistante et sans lien
avec cette décision : contrairement aux contrôles de prix, l'archivage de
la facture porteuse ne la retire pas sur-le-champ — elle est levée au
prochain passage des contrôles différés où R06 est active, balayage global
de la portée suivi). Une adaptation front, oubliée lors de la désactivation
initiale et corrigée après relecture (constat 1) : l'écran Réglages signale
désormais sans effet le seuil propre à R06, « Délai avant alerte d'une
ligne de BL non facturée » (`delai_ligne_bl_non_facturee_j`), même
mécanisme que les trois seuils de prix mais drapeau distinct
(`CompteProblemesReponse.controle_livre_non_facture_actif`, exposé par
`GET /api/a-regler/compte` aux côtés de `controle_prix_actif`).

> **Remplacé depuis** : ce signalement « sans effet » côté front est
> remplacé par un masquage côté serveur (`ingest.parametres._cle_masquee`,
> `GET /api/parametres` ne renvoie plus ce seuil tant que R06 est
> désactivée, `PUT` le refuse comme une clé inconnue) —
> `CompteProblemesReponse.controle_livre_non_facture_actif`, décrit
> ci-dessus, n'existe plus, voir `infra/README.md` §2.5.

Les écrans d'anomalies, eux, ne changent pas : R06 était déjà rangée dans
la catégorie « Quantités » (`ingest.anomalies.CATEGORIES_REGLE`), jamais un
libellé ou un filtre qui lui soit propre sur ces écrans-là — la tuile
« Écart de quantité » et son sous-texte (« livraisons avec un écart de
quantité ») restent corrects sans changement, R02 (« Livré sans bon »,
preuve dans la facture) reste active. Réactivation : variable dans le
fichier d'environnement de l'instance (`.env.prod` / `.env.demo`) puis
recréation du conteneur API (`up -d api`), voir
`docs/evolutions-proposees.md` §c, sans interrupteur à l'écran.

**Troisième addendum du 25/09/2026 — décision (déjà prise, pas à valider) :
la tuile « Écart de quantité » de la Vue d'ensemble est remplacée par
« Montant des bons reçus ».** L'accueil se construit à partir des
factures : un bon validé mais pas encore retrouvé sur une facture n'y
apparaissait nulle part, alors qu'Ilane veut voir tout de suite ce qui a
été livré, facture ou non. La 3e tuile de `VueEnsemble.tsx`
(`libelleEcart`/`sousTexteEcart`, `totaux.en_ecart`) devient « Montant des
bons reçus », à partir de trois champs ajoutés à `GET /api/tableau-de-bord`
(`ingest.tableau_de_bord._compter_bons_recus`) : `nb_bons_recus` (documents
de type bon -- BL et enlèvement, `ingest.lecture.TYPES_BL` -- au statut
`recu` du mois affiché, jamais `a_verifier` ni `archive`),
`montant_bons_recus` (somme de leur `total_ht`, `0` si aucun) et
`nb_bons_sans_montant` (parmi ces bons reçus, ceux dont `total_ht` est
`NULL` -- comptés dans `nb_bons_recus` mais jamais dans le montant,
beaucoup de bons n'ayant aucun prix imprimé). Un bon compte qu'il soit ou
non déjà retrouvé sur une facture : notion différente de `nb_bl_recus`, qui
compte des blocs de facture rapprochés, pas des bons. Limites : pas de
filtre agence (le tableau de bord n'en a pas) ; `libelleEcart`/
`sousTexteEcart` (second addendum ci-dessus) restent utilisés tels quels
par la fiche chantier et la fiche fournisseur, seul l'accueil change.

## 4. Contrôles finaux (sur `f1404bc`)

```
uv run pytest -q            → 1610 passed in 441.13s
uv run ruff check            → All checks passed!
uv run ruff format --check   → 235 files already formatted
uv run mypy                  → Success: no issues found in 198 source files
npm --prefix web run typecheck  → sans erreur
npm --prefix web run build      → build réussi
```

## 5. Déploiement du 23/09/2026

Sauvegarde préalable des deux bases (`pg_dump -Fc`) dans
`~/sauvegardes-habitat/`, puis pour chaque instance (démo et production,
voir `docs/deploiement-et-tests.md` §1.1) : reconstruction de l'image API,
arrêt de l'API, `alembic upgrade head` (migration `0009` → `0010`, colonne
`chantier.client`), redémarrage — les deux instances sont reparties saines.
Des clients fictifs ont été renseignés sur les cinq chantiers de la base de
démonstration (donnée de démo uniquement, aucun impact en production). Le
webhook Telegram n'a pas été touché et reste fonctionnel sur les deux
instances.

## 6. Points ouverts

- **Google Drive toujours bloqué**, pour une raison précise cette fois : le
  compte de service ne peut pas écrire sur un Drive personnel. Il faut soit
  un dossier sur un Drive **partagé** Google Workspace, soit basculer
  l'authentification en **OAuth** utilisateur — aucune des deux options
  n'est en place. `drive-sync` reste donc non exécutable en conditions
  réelles ; ne pas poser son cron avant d'avoir tranché.
- **Fournisseurs à enregistrer en production** : SIRET et numéro de TVA
  d'Unikalo (visibles sur la facture d'août) et de Point.P (à demander,
  aucune facture Point.P disponible à ce jour — dette héritée du lot 3).
- **Chantiers et alias d'août à valider en production** avant de considérer
  le classement du mois comme une vérité métier acceptée (report des
  réserves déjà posées au lot 4 et au lot 5).
- **Quatre photos de BL réelles à renvoyer « en tant que fichier »** sur
  Telegram (envoyées jusqu'ici compressées comme photo, ce qui dégrade la
  lecture OCR) — toujours seulement 4 sur les 30 exigées par le CDC §10.
- **Secrets collés en clair pendant la session à faire tourner** après la
  démo : la clé Mistral, le jeton du bot Telegram, la clé du compte de
  service Google.
- **Sauvegardes restic et tâches planifiées non posées** sur les deux
  instances désormais en service (démo et production) : seules des
  sauvegardes manuelles ponctuelles existent à ce jour, voir
  `docs/dette.md`.
- **Lot 6 (Livraison, CDC §11) non commencé** : recette sur deux mois de
  documents, corrections, documentation d'exploitation, formation de deux
  heures, remise du dépôt.

**Mineurs reportés** (détail complet, constat par constat, dans
`docs/dette.md`, section « Revue finale de la refonte du front » et les
sections par tâche) :

- **Navigation et liens résiduels** : quelques liens internes pointent
  encore vers d'anciennes routes redirigées, un sous-lien de menu fait
  doublon avec « Chantiers », la page BL reste accessible sous deux URL
  sans canonique unique, et revenir depuis un problème traité mène toujours
  à la liste « À régler » plutôt qu'à la fiche chantier ou fournisseur
  d'origine.
- **Composants partagés incomplets** : pas encore de composant `Tableau` ni
  `Barre latérale` communs dans `web/src/ui/` (chaque écran a le sien), et
  quelques aides/libellés dupliqués entre écrans.
- **Filtres hérités non repris** : les filtres fins de l'ancien écran
  Anomalies (règle précise, période, « traitées » séparées des
  « ignorées ») n'existent plus tels quels ; seul « Voir l'historique »
  d'une fiche chantier ou fournisseur y ramène.
- **Exports CSV inchangés** : le client du chantier n'apparaît dans aucun
  export, et les en-têtes du lot 5 gardent leurs termes techniques (codes
  de règle compris).
- **Ergonomie résiduelle** : des cibles tactiles sous 44 px héritées de
  presque tous les écrans du projet (pas une régression de cette refonte),
  pas de bandeau d'erreur global (chaque section gère ses propres erreurs
  réseau).
- **Écarts fonctionnels mineurs assumés** : le montant « Sans bon de
  livraison » reste un fait qui ne baisse pas quand un problème est traité
  ou ignoré (distinct du nombre de problèmes et de l'état du chantier, qui
  eux baissent) ; le numéro interne d'un document reste affiché sur la page
  BL car c'est le seul moyen de le retrouver depuis un message Telegram.

Cette recette ne remplace pas une validation client : les captures et
vérifications visuelles utilisent uniquement des données fictives, et
aucune des définitions monétaires héritées du lot 5 n'a été reconfirmée à
l'occasion de cette refonte.
