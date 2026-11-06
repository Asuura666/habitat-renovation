# Contrôle BL & factures — Habitat & Rénovation

Application qui collecte les bons de livraison (photos envoyées sur Telegram)
et les factures fournisseurs (PDF), lit leur contenu, les rapproche et signale
les anomalies avec une règle nommée et une justification chiffrée. Un seul
client, une seule instance, en production sur `habitat.ellumena.fr`.

**État au 04/11/2026** : en production, code `3399c6e` (PR #29), migration
`0018`, 3 115 tests verts. IA éteinte et gelée. Attendu du client : les
factures fournisseurs d'octobre.

> Ce README est la porte d'entrée. L'ancien README (2 180 lignes, état au
> 22/10/2026, complété par endroits le 02/11) est gardé tel quel dans
> [`docs/readme-octobre-2026.md`](docs/readme-octobre-2026.md), avec les mêmes
> numéros de section (« archive §N » ci-dessous). Il garde l'histoire détaillée,
> l'audit du 29/09, le déroulé jour par jour et la liste des anciennes PR.

## Sommaire

1. [Résumé](#1-résumé)
2. [État au 04/11/2026](#2-état-au-04112026)
3. [Parcours d'un bon et d'une facture](#3-parcours-dun-bon-et-dune-facture)
4. [Écrans](#4-écrans)
5. [Lecture des bons : confiance et vérifications](#5-lecture-des-bons--confiance-et-vérifications)
6. [Règles R01 à R25](#6-règles-r01-à-r25)
7. [Architecture et frontières](#7-architecture-et-frontières)
8. [Données et migrations 0001 à 0018](#8-données-et-migrations-0001-à-0018)
9. [Configuration](#9-configuration)
10. [Démarrer en local, tests et qualité](#10-démarrer-en-local-tests-et-qualité)
11. [Commandes CLI](#11-commandes-cli)
12. [Déploiement et retour arrière](#12-déploiement-et-retour-arrière)
13. [Exploitation](#13-exploitation)
14. [Sécurité et RGPD](#14-sécurité-et-rgpd)
15. [IA](#15-ia)
16. [Organisation du travail](#16-organisation-du-travail)
17. [Historique en bref](#17-historique-en-bref)
18. [Limites connues et ce qui attend le client](#18-limites-connues-et-ce-qui-attend-le-client)
19. [Index de la documentation](#19-index-de-la-documentation)

---

## 1. Résumé

**Ce que fait l'application.** Les employés photographient leurs bons de
livraison (BL) et bons d'enlèvement dans un groupe Telegram. L'application lit
chaque photo (OCR Mistral), reconnaît le fournisseur et le chantier, enregistre
les lignes, puis les compare aux factures fournisseurs déposées en PDF. Elle
affiche ce qui ne colle pas dans un écran « À régler », avec la raison et les
chiffres.

**Pour qui.** Un admin (la direction, Ilane) traite les problèmes, suit les
chantiers et les fournisseurs. Les employés déposent leurs photos sur Telegram
et ne voient dans l'application que leurs propres dépôts.

**Le principe.** L'IA lit, les règles décident, l'humain tranche.

- L'OCR et la normalisation lisent et rangent. Elles ne décident jamais.
- Une anomalie ne naît que d'une règle déterministe (`R01` à `R25`), qui porte
  son nom et une justification chiffrée.
- Une personne traite, conteste ou ignore chaque problème, avec un commentaire.
  Une anomalie traitée ou ignorée n'est jamais rouverte.
- Les contrôles de prix comparent des chiffres à une grille ou à un dernier
  prix facturé. Aucun modèle de langage n'intervient dans la décision.

**Stack imposée** (détail : `CLAUDE.md`, archive §7). Python 3.11, uv, FastAPI,
SQLAlchemy 2 async, Alembic, PostgreSQL 18 ; React 18, TypeScript, Vite,
TanStack Query, Tailwind ; Docker Compose, nginx (Traefik prévu pour le serveur
dédié), restic ; ruff, mypy strict, pytest. Interdits : n8n, Redis, Celery,
S3, LangChain, tout autre ORM.

---

## 2. État au 04/11/2026

### 2.1 Production

| Élément | Valeur |
| --- | --- |
| Adresse | `habitat.ellumena.fr` (une seule instance) |
| Code déployé | `3399c6e` (PR #29), le 02/11/2026 à 22 h 27 UTC |
| Migration | `0018` |
| `main` | Aligné sur la production le 04/11/2026 (PR #30, `0f533af`, étiquette `mise-en-prod-2026-11-02`) |
| `dev` | `main` plus la PR #31 (hôte de démonstration retiré de `deploy/nginx/habitat.conf`, fichier déjà identique sur le serveur : rien à redéployer) |
| Démonstration | Supprimée le 29/10/2026 (conteneurs et base ; la base est archivée sur le serveur) |
| Tests | 3 115 au 04/11/2026 |

### 2.2 Ce qui est allumé, éteint, retiré

| Fonction | État | Où ça se règle |
| --- | --- | --- |
| IA (synthèse des commentaires, avis sur les prix, prix internet) | **Éteinte** en production, **gelée** par Ilane depuis le 29/09 | `IA_ACTIVE=false` |
| Contrôle des prix des bons (R19 à R25) | **Allumé** | Réglage `prix_controle_bl_actif` (écran Réglages) |
| R06 « Livré mais pas facturé » | Désactivée côté serveur | `CONTROLE_LIVRE_NON_FACTURE_ACTIF` (défaut `false`) |
| R07, R08, R09 (prix à la facture) | Désactivées côté serveur | `CONTROLE_PRIX_ACTIF` (défaut `false`) |
| R15 « Quantités non confirmées par l'équipe » | **Retirée** le 31/10/2026 | Migration `0017` ; plus de boutons de confirmation sous « Reçu » |
| Synchronisation Google Drive | Codée, jamais exécutée en réel (bloquée) | `drive-sync` non planifiée |
| Supervision Telegram | **Aucune alerte ne sort du serveur** | Voir §13.3 |

### 2.3 Données chargées

- Grilles de prix chargées en production : Unikalo, Point.P, Rexel, Corudo.
- Historique Point.P importé depuis le fichier de contrôle d'août
  (`importer-historique-prix`).
- Environ 11 fournisseurs au référentiel.
- « Méridionale Bois et Matériaux » est la société qui exploite Point.P dans la
  région (son nom est en pied de page des bons Point.P). Elle a été fusionnée
  dans Point.P le 02/11/2026 (`fournisseur-fusionner`).

### 2.4 Ce qui attend le client

- Les **factures fournisseurs d'octobre en PDF** (demandées le 04/11/2026) :
  sans elles, aucun bon d'octobre ne se rapproche d'une facture.
- Aucune facture Point.P n'a été reçue : le lecteur de factures Point.P
  n'existe pas (voir §18).
- Le **lot 6** (recette sur deux mois, formation, procès-verbal de réception)
  n'est pas commencé.
- Le **serveur dédié** au nom du client et les **sauvegardes hors du serveur**
  sont une décision du client, pas d'Ilane (Ilane, 04/11/2026).

### 2.5 Décisions en attente

- **Proposition en attente d'Ilane** : ne plus lever « Produit absent de la
  grille » (R22) pour un fournisseur qui n'a aucune grille.
- Définitions à confirmer par le client : les quatre montants du Bilan, le
  classement d'août, « Conforme » strict (archive §23.1).
- Avenant IA (cahier des charges §15) : rédigé, « à confirmer ».

---

## 3. Parcours d'un bon et d'une facture

### 3.1 Dépôt d'un bon par Telegram

Un employé envoie la photo de son bon dans le groupe Telegram des bons
(`POST /tg/webhook`). Il peut taper le nom du chantier en **légende** de la
photo : la légende sert de confirmation du chantier.

1. Le webhook dédoublonne l'update Telegram, ignore les autres groupes et les
   messages texte seuls.
2. L'expéditeur est rattaché à un compte. Au premier envoi d'un employé inconnu,
   son compte est **créé automatiquement** ; un compte désactivé est refusé avec
   une réponse dans le groupe.
3. En tâche de fond : téléchargement, vérification de la **signature du
   fichier** (pas seulement le type annoncé) et de la taille, écriture sur
   disque, enregistrement du document (statut `recu`). Le téléchargement est
   tenté jusqu'à 3 fois (pauses de 1 s puis 3 s). La raison de chaque refus de
   Telegram est notée dans le journal, sans le token ni l'adresse.
4. OCR Mistral, lecture structurée du bon, normalisation (§5), rattachement du
   fournisseur et du chantier, enregistrement des lignes.
5. Si un numéro de BL est lu, rapprochement avec les factures déjà déposées.
6. Un lien physique de la photo est posé sous
   `<DOCS_DIR>/bl/<AAAA>/<MM>/<JJ>_<déposant>_<chantier>_n<numéro>.<ext>`.
   Ce n'est **pas** une sauvegarde (même disque).
7. Le bot répond « Reçu — document n° N », **sans bouton** (la confirmation des
   quantités est retirée depuis le 31/10/2026 ; les boutons des anciens messages
   marchent encore). En cas d'échec d'enregistrement, il répond « Échec de
   l'enregistrement, renvoyez la photo. » ; ce message part après le dernier
   essai de téléchargement.

Un bon d'enlèvement est traité comme un BL.

### 3.2 Statut « reçu » ou « à vérifier »

Un document a trois statuts : `recu`, `a_verifier`, `archive`. Un bon est
« à vérifier » **seulement s'il lui reste au moins un motif**. Les motifs
viennent de `app/modules/extract/verification.py` (`CodeMotif`) :

| Motif | Sens |
| --- | --- |
| `champ_absent`, `valeur_illisible`, `confiance_faible` | Un champ manque, est illisible ou lu avec une confiance trop basse |
| `somme_incoherente`, `total_absent`, `lignes_absentes` | La somme des lignes ne tombe pas sur le total, ou le total ou les lignes manquent |
| `numero_incoherent`, `numero_en_double` | Le numéro de BL lu diffère du numéro détecté, ou existe déjà chez ce fournisseur |
| `fournisseur_inconnu` | Aucun fournisseur du référentiel ne correspond |
| `reference_chantier_inconnue` | Pas de chantier écrit sur le bon et la référence de commande ne désigne aucun chantier connu |
| `calcul_ligne_incoherent` | Quantité × prix ne donne pas le montant lu de la ligne |
| `ocr_echec`, `annotation_illisible` | La lecture a échoué ou n'est pas exploitable |

Chaque motif porte un détail chiffré. L'historique du bon dit ce qui a été
confirmé. Un admin corrige, valide ou relance la lecture depuis la page du bon.

### 3.3 Contrôle des prix d'un bon

Après la lecture d'un bon ou la correction de ses lignes, si le contrôle est
allumé (§2.2), chaque ligne est comparée à la grille du fournisseur (prix en
vigueur à la date du bon) et au dernier prix facturé. Les règles R19 à R25 (§6.2)
créent les alertes. La page « Prix à vérifier » liste les produits en alerte :
l'admin **valide** (le prix du bon entre dans la grille), **conteste**
(commentaire obligatoire, la grille ne bouge pas) ou **ignore**.

### 3.4 « À régler »

L'écran « À régler » réunit ce qui attend une décision : problèmes ouverts
(anomalies), documents à corriger, chantiers à rattacher ou à confirmer. Traiter
un problème exige un commentaire (« Contesté auprès du fournisseur » ou « C'est
normal, ignorer »). Un problème ignoré n'est pas recréé pendant 90 jours
(réglage `duree_ignorance_j`).

### 3.5 Dépôt d'une facture

L'admin dépose le PDF sur l'écran Documents (20 Mo au plus). Traitement
synchrone : signature PDF, OCR Mistral, lecture par le parseur du fournisseur,
détection de doublon, enregistrement, rapprochement. **Seul le format Unikalo est
lu** (`extract/unikalo.py`) ; une autre facture donne « Format de facture non
pris en charge ».

### 3.6 Rapprochement bon et facture

Chaque bloc « Concerne le B.L. n°… » d'une facture est comparé au bon du même
numéro chez le même fournisseur (statut `recu`, `non_recu` ou `pas_de_bon`). Les
lignes sont appariées par code puis par désignation, converties dans l'unité de
facturation, puis le moteur de règles évalue les anomalies (R01 à R05, R10 à
R13, R17). Le rapprochement est **idempotent** : il se rejoue à chaque nouvel
événement (`rapprocher`, §11).

### 3.7 Livraisons, archivage, exports

- L'écran « Livraisons » montre une ligne par bloc de facture **et** une ligne
  par bon qu'aucune facture n'a encore repris, avec une colonne « Facturé ».
- Un bon n'est « facturé » que si le bloc d'une facture **non archivée** le cite.
- « Archiver » (page d'un bon ou d'une facture) retire le document de tous les
  comptes ; les bons d'une facture archivée redeviennent « non facturés ». Une
  facture archivée par erreur ne se rétablit pas depuis l'application.
- Exports CSV (`/api/bilan/chantiers.csv`, `fournisseurs.csv`, `detail.csv`,
  `livraisons.csv`) depuis les écrans.

---

## 4. Écrans

Routes de `web/src/App.tsx`. Un agent ne voit que Documents (ses dépôts, en
lecture) ; toute route admin le renvoie vers `/documents`. Les anciennes adresses
(`/a-traiter`, `/anomalies`, `/bilan…`, `/bl`, `/factures…`) redirigent vers les
nouvelles.

| Écran | Route | Accès | Ce qu'on y fait |
| --- | --- | --- | --- |
| Connexion | `/connexion` | Public | Se connecter (cookie httpOnly, 12 h glissantes) |
| Vue d'ensemble | `/` | Admin | Mois au choix ; chiffres du mois ; tuile « Montant des bons du mois » (tous les bons non archivés, vérifiés ou non, avec « dont N à vérifier » et « K sans montant lu ») ; suivi des chantiers du mois (nombre et montant des bons, bons à vérifier, problèmes ouverts, facturé ou « Pas encore », ligne « Sans chantier ») ; problèmes prioritaires ; lien « N factures ce mois-ci » vers la liste des factures ; carte de synthèse des commentaires (alimentée par l'IA) |
| À régler | `/a-regler`, `/a-regler/:id` | Admin | File unique des décisions à prendre ; détail avec « pourquoi c'est signalé » chiffré ; choix du chantier sur une alerte R18 ; avis de l'IA sur une alerte de prix (IA éteinte : absent) |
| Chantiers | `/chantiers`, `/chantiers/:id` | Admin | « Chantiers du mois » ou « Tous les chantiers » ; recherche par nom ou client ; filtres mois et agence ; création ; fiche (client, agence, livraisons, chiffres) ; chantiers « à compléter » ; fusion de deux chantiers |
| Fournisseurs | `/fournisseurs`, `/fournisseurs/:id` | Admin | Liste ; fiche avec carte « Factures » (non archivées, suit le mois), chantiers concernés, filtre par mois, problèmes ouverts |
| Grille de prix | `/fournisseurs/:id/prix` | Admin | Prix en vigueur, ajout ou modification (nouvelle ligne d'historique, jamais d'écrasement), retrait, import Excel avec aperçu et modèle à télécharger ; « Historique » d'un produit (versions de la grille, prix vus sur les bons et factures par la référence, prix observés importés) ; contestations de prix |
| Livraisons | `/livraisons` | Admin | Lignes de facture et bons non facturés (colonne « Facturé »), filtrables par mois, agence, chantier, fournisseur ; le montant d'un bon non facturé est le montant lu sur le bon ; export CSV |
| Prix à vérifier | `/prix` | Admin | Une rangée par produit en alerte (prix du bon, grille et sa date, dernier prix facturé, écart) ; Valider, Contester, Ignorer ; recontrôle des bons ; colonne « Internet » seulement si l'IA est allumée |
| Documents | `/documents`, `/documents/:id`, `/bl/:id` | Admin ; agent (ses dépôts) | Liste filtrable ; dépôt d'une facture PDF (admin) ; page d'un bon : photo, téléchargement nommé, tableau livré / facturé / prix / contrôle par ligne, correction de lecture, validation, archivage, relance de la lecture, commentaires par ligne (non modifiables) |
| Comptes | `/comptes` | Admin | Créer, modifier, changer le mot de passe, retirer ou rétablir l'accès |
| Journal | `/journal` | Admin | Journal des actions en français, avec lien vers l'élément concerné |
| Réglages | `/reglages` | Admin | Seuils modifiables, interrupteurs du contrôle des prix, lien « Essayer l'IA » |
| Laboratoire IA | `/ia` | Admin | Diagnostic et essais de l'IA, sans rien enregistrer |

Principes du front : téléphone d'abord (barre de navigation basse), aucun jargon
(`web/src/ui/libelles.ts` traduit chaque code de règle), TanStack Query avec
données fraîches 30 s, types générés depuis l'API (`npm --prefix web run
api:schema` puis `api:types`). Détail : archive §11.

---

## 5. Lecture des bons : confiance et vérifications

Ces règles datent des lots du 31/10 au 02/11/2026 (PR #26 à #29). Elles
s'appliquent à la lecture d'un bon et, sans nouvel OCR, aux bons déjà reçus
(`recalculer-bons`, `resoudre-fournisseurs`).

### 5.1 Fournisseur

Un fournisseur est résolu par **SIREN** (9 premiers chiffres du SIRET lu), puis
par **numéro de TVA**, puis par **nom** : la première étape qui désigne un
fournisseur unique conclut, une étape ambiguë passe à la suivante
(`normalize/fournisseur.py`). Un fournisseur reconnu par son SIREN ou sa TVA
n'est plus « à vérifier » pour la lecture de son nom. Aucun fournisseur n'est
créé automatiquement : le référentiel s'alimente par `fournisseur-definir`.
Sans correspondance : motif `fournisseur_inconnu`.

### 5.2 Chantier

Le chantier est cherché à partir de trois sources, dans cet ordre.

1. **Le nom lu sur le bon**, nettoyé avant comparaison et avant toute création
   de chantier : on retire les mots qui sont des mots du nom d'un compte
   (prénoms et noms des employés, trois lettres au moins) et les mots de liaison
   « pour », « par », « pris », « prs », « cde », « commande », « commandé »,
   « enlevé ». Un nom vide après nettoyage passe à la source suivante. Le nom lu
   enregistré sur le bon ne change pas.
2. **La légende Telegram** de la photo.
3. **La « Référence commande client »**, seulement si ni le nom ni la légende ne
   donnent de chantier. Elle est ignorée si elle a moins de trois lettres, si
   elle est surtout faite de chiffres ou si tous ses mots sont des mots du nom
   d'un compte. Si elle ressemble à un chantier connu, le bon y est rattaché
   (jamais de création de chantier ni d'alias appris depuis une référence) ;
   sinon le bon reste sans chantier et « À régler » le dit, avec la référence
   lue (motif `reference_chantier_inconnue`).

Règles de décision (`normalize/chantier.py`, `ingest/rattachement_chantier.py`) :

- **Seuil de ressemblance : 80 %** par défaut (réglage
  `seuil_ressemblance_chantier_pct`, bornes 50 à 100 ; 90 % avant le
  31/10/2026). Une ressemblance d'au moins le seuil rattache le bon ; sinon un
  chantier est créé automatiquement, marqué « à compléter », et signalé dans
  « À régler ».
- Deux noms qui ne diffèrent que par un nombre (« … 12 » et « … 13 ») ne sont
  jamais rattachés automatiquement : ils sont proposés « à confirmer ».
- Si le nom lu et la légende désignent deux chantiers différents, ou plusieurs
  candidats à égalité, la règle **R18 « Chantier à confirmer »** est levée et un
  humain choisit.
- Le chantier est **confirmé** (le motif de lecture incertaine du nom de
  chantier tombe) quand le nom est connu ou ressemble à un chantier, ou quand la
  légende le désigne. Un chantier « à compléter » (créé automatiquement) ne
  confirme jamais sa propre lecture.
- Un **chantier choisi à la main** n'est jamais écrasé par une relecture et
  compte comme identifié.

### 5.3 Lignes

La confiance d'une ligne repose sur la **quantité, le prix unitaire et le
montant trouvés ensemble** dans le texte lu. Le code et la désignation ne
comptent plus. En plus, le contrôle **quantité × prix = montant**
(`extract/arithmetique.py`) accepte un écart d'un centime plus la moitié de la
dernière décimale imprimée du prix, multipliée par la quantité (les prix
imprimés sont arrondis). Un calcul faux donne le motif
`calcul_ligne_incoherent`, avec le calcul en détail. Limites : le schéma de
lecture ne porte pas de remise, donc une ligne remisée peut échouer ce contrôle
à tort ; le contrôle n'est pas rejoué après une correction humaine des lignes.
Voir `docs/dette.md`.

### 5.4 Totaux

La somme des lignes est comparée au total HT lu. Au-delà de la tolérance
(`tolerance_total_ht`, quelques centimes), le document passe « à vérifier »
(`somme_incoherente`), et la règle R10 (facture) ou R11 (bon) lève un problème.

---

## 6. Règles R01 à R25

Chaque règle est une fonction pure dans `app/modules/rules/rules/Rxx.py` : elle
reçoit des dataclasses et rend une `Anomalie` (règle, gravité, `detail` chiffré
jamais vide) ou rien. Au moins un test positif et un test négatif par règle.
Catalogue de référence : `ARCHITECTURE.md` §8 et archive §5.

### 6.1 R01 à R18

| Règle | Nom | Ce qu'elle vérifie | État |
| --- | --- | --- | --- |
| R01 | Bon de livraison jamais reçu | Bloc de facture sans bon déposé de même numéro | Active |
| R02 | Livré sans bon | Bloc facturé avec la mention « pas de bon » ou « sans bon » (exclusive de R01) | Active |
| R03 | Facturé plus que livré | Quantité facturée supérieure à celle du bon | Active |
| R04 | Facturé moins que livré | Quantité facturée inférieure à celle du bon | Active |
| R05 | Facturé mais absent du bon | Ligne facturée sans ligne de bon correspondante | Active |
| R06 | Livré mais pas facturé | Ligne d'un bon déjà rapproché restée non facturée après `delai_ligne_bl_non_facturee_j` jours | **Désactivée côté serveur** (`CONTROLE_LIVRE_NON_FACTURE_ACTIF=false`) ; contrôle différé |
| R07 | Prix un peu plus cher | Prix facturé au-dessus de la médiane des 6 derniers mois de `seuil_prix_pct` | **Désactivée côté serveur** (`CONTROLE_PRIX_ACTIF=false`) |
| R08 | Prix plus cher que d'habitude | Même calcul, au-dessus de `seuil_prix_fort_pct` | **Désactivée côté serveur** (idem) |
| R09 | Remise habituelle oubliée | Article habituellement remisé, facturé sans remise | **Désactivée côté serveur** (idem) |
| R10 | Erreur de calcul sur la facture | Somme des blocs différente du total HT, au-delà de la tolérance. Évaluée seule pour une facture « à vérifier » | Active |
| R11 | Erreur de calcul sur le bon | Somme des lignes différente du total HT du bon | Active |
| R12 | Bon facturé deux fois | Même numéro de bon dans deux factures du même fournisseur | Active |
| R13 | Avoir sans achat d'origine | Ligne négative sans ligne positive d'origine | Active |
| R14 | Chantier à rattacher | Alias de chantier non résolu après `delai_alias_non_resolu_h` heures | Active, contrôle différé |
| R15 | Quantités non confirmées par l'équipe | — | **Retirée** le 31/10/2026 (`REGLES_RETIREES`) ; problèmes ouverts fermés par la migration `0017` |
| R16 | Chantier sans bon déposé récemment | Aucun bon déposé depuis `delai_chantier_silencieux_j` jours alors que des factures y renvoient | Active, contrôle différé |
| R17 | Quantité inhabituelle pour le conditionnement | Nombre de conditionnements non entier alors que le ratio de l'article est connu et validé | Active |
| R18 | Chantier à confirmer | Nom lu et légende désignent deux chantiers, ou plusieurs candidats à égalité | Active |

La règle « semi-remorque » du cahier des charges n'a jamais été construite
(aucun déclencheur défini par le client).

Trois points d'entrée dans le moteur (`rules/engine.py`) : `evaluer_facture`
(à chaque rapprochement), `evaluer_suivi` (R06, R14, R16 par la commande
`controles-differes`) et `evaluer_chantier` (R18, au rattachement). Une règle
désactivée n'est ni évaluée ni comptée ; ses anomalies déjà ouvertes restent en
base, masquées des écrans, jusqu'à réactivation (`ingest/commun.py`,
`regles_desactivees`, seule fonction qui lit ces drapeaux).

### 6.2 R19 à R25 — contrôle des prix d'un bon

Évaluées après la lecture d'un bon ou la correction de ses lignes
(`ingest/prix_bl.py`). Chaque alerte a son interrupteur dans Réglages, derrière
l'interrupteur général `prix_controle_bl_actif` (éteint par défaut, **allumé en
production**). Le prix lu sur un bon est considéré comme net et comparé au prix
net de la grille, après conversion d'unité quand le ratio de l'article est connu.

| Règle | Nom | Ce qu'elle vérifie | Réglage propre |
| --- | --- | --- | --- |
| R19 | Plus cher que la grille | Prix du bon au-dessus du prix de grille en vigueur, plus `prix_seuil_hausse_pct` (0 % par défaut) | `prix_alerte_plus_cher_grille` |
| R20 | Plus cher que la dernière fois | Prix du bon au-dessus du dernier prix facturé du produit chez ce fournisseur | `prix_alerte_plus_cher_dernier_prix` |
| R21 | Moins cher que la grille | Prix du bon au-dessous du prix de grille de plus de `prix_seuil_baisse_pct` (5 % par défaut) ; gravité basse | `prix_alerte_moins_cher_grille` |
| R22 | Produit absent de la grille | Aucun produit de grille retrouvé, ni par référence ni par nom | `prix_alerte_absent_grille` |
| R23 | Reconnu seulement par son nom | Produit retrouvé par ressemblance de désignation, pas par référence | `prix_alerte_reconnu_par_nom` |
| R24 | Unités différentes | Unité du bon et de la référence non convertibles : aucune comparaison de prix | `prix_alerte_unites_differentes` |
| R25 | Grille ancienne | Prix de grille plus vieux que `prix_age_grille_mois` (12 mois par défaut) | `prix_alerte_grille_ancienne` |

« Contester » ferme toutes les alertes du produit au statut « traitée » avec le
commentaire « Contesté : … » (obligatoire), l'auteur et la date, écrit une
entrée au journal par alerte, et ne touche jamais la grille. Une alerte fermée
n'est jamais rouverte. Le contrôle de prix à la **facture** n'existe pas.

Quels interrupteurs individuels sont allumés en production : **à confirmer** dans
l'écran Réglages.

---

## 7. Architecture et frontières

Monolithe modulaire. Une instance = un projet Docker Compose (`habitat_prod`)
avec une API (FastAPI, qui sert aussi le front compilé) et une base PostgreSQL,
derrière nginx. Un conteneur OpenCode séparé existe pour l'IA (projet
`habitat_ia`), jamais exposé. Schémas détaillés : `ARCHITECTURE.md` ; consignes
de travail : `CLAUDE.md`.

```
app/main.py, app/cli.py    point d'entrée FastAPI (/health, config fail-fast) ; commandes d'exploitation
app/core/                  config, db, auth, origine (anti-CSRF), service du front, fuseau
app/modules/ingest/        SEUL ORCHESTRATEUR : webhook, dépôts, rapprochement, anomalies, bilan, grilles, IA, modèles SQL
app/modules/extract/       PUR — OCR, lecture des bons et des factures (unikalo.py), confiance, vérification
app/modules/normalize/     PUR — fournisseur, chantier, article, unités, prix, ressemblance
app/modules/rules/         PUR — engine.py, rules/R01.py à R25.py
app/modules/api/           routeurs JSON (préfixe /api) ; messaging/ (Telegram) ; jobs/ (Drive, bloqué)
web/  migrations/  deploy/  docs/  infra/  tests/
```

Règles de frontière, non négociables :

- `extract`, `normalize`, `rules` n'importent ni FastAPI, ni SQLAlchemy, ni
  httpx. Dataclasses en entrée et en sortie ; leurs tests tournent sans base ni
  réseau.
- Aucun module métier n'en importe un autre, sauf `ingest`, seul orchestrateur.
  `api` et `jobs` n'importent que `ingest` et `app.core`.
- Aucune règle métier dans le front ni dans un routeur : le routeur valide,
  appelle un service, sérialise.
- Vérifié par `tests/test_frontieres.py` (analyse statique des imports par
  `ast`). `app/core`, `app/main.py` et `app/cli.py` échappent à cette garde
  (exceptions assumées).

Les migrations ne tournent jamais au démarrage du conteneur : elles s'appliquent
à la main, API arrêtée.

---

## 8. Données et migrations 0001 à 0018

`app/modules/ingest/models.py` est la source de vérité du schéma. Conventions :
identifiants UUID générés par la base ; listes fermées en `text` avec un `CHECK`
nommé, jamais un `ENUM` ; aucune suppression physique de document (statut
`archive`) ; journal, commentaires et grilles de prix en ajout seul.

Tables principales : `fournisseur`, `agence_fournisseur`, `chantier`,
`chantier_alias`, `article`, `document`, `bloc_facture`, `ligne`,
`rapprochement_ligne`, `anomalie`, `commentaire`, `utilisateur`, `jeton_session`,
`journal`, `parametre`, `telegram_update`, `grille_import`, `grille_prix`
(UPDATE, DELETE et TRUNCATE refusés par des déclencheurs), `prix_observe`, et
les tables de l'IA (`appel_ia`, `synthese_commentaires`, `synthese_action`,
`explication_alerte`, `prix_internet`).

| Révision | Objet |
| --- | --- |
| 0001 | Schéma initial (14 tables du cahier des charges) |
| 0002 | `jeton_session` (sessions de connexion) |
| 0003 | Numéro interne, photo compressée, total HT du document |
| 0004 | Ordre des blocs de facture |
| 0005 | Colonnes d'extraction du document, confiance des lignes, motifs |
| 0006 | Anomalies : article et clé d'unicité |
| 0007 | Anomalies : chantier et alias dans l'identité |
| 0008 | Données seules : `bloc_id` complété pour les anciennes anomalies |
| 0009 | Suivi de la synchronisation Drive |
| 0010 | `chantier.client` |
| 0011 | `document.legende`, `chantier.a_completer`, `chantier.fusionne_dans_id` (rattachement automatique des chantiers) |
| 0012 | Table `commentaire` (ajout seul) |
| 0013 | Grilles de prix : `grille_import`, `grille_prix` (historique inaltérable) |
| 0014 | Tables de l'IA |
| 0015 | `prix_internet.offres` (jusqu'à cinq offres) |
| 0016 | `synthese_commentaires.nb_contestations` |
| 0017 | Fermeture des problèmes R15 encore ouverts (31/10/2026) ; aucune structure modifiée |
| 0018 | Table `prix_observe` (prix observés importés pour l'historique d'un produit, jamais dans la grille) |

Ne jamais lancer `alembic downgrade` en production : un retour arrière restaure
ensemble le code, la base et les documents (§12.4).

---

## 9. Configuration

Noms de variables seulement. Aucune valeur ne doit apparaître dans le dépôt, un
commit, un journal ou un ticket. `app/core/config.py` (`Settings`) refuse de
démarrer si une variable obligatoire manque, en nommant la variable.

### 9.1 Lues par l'application

| Variable | Obligatoire / défaut | Rôle |
| --- | --- | --- |
| `DATABASE_URL` | Obligatoire | Connexion PostgreSQL |
| `DOCS_DIR` | Obligatoire | Dossier des documents originaux (`/srv/docs` dans le conteneur) |
| `TELEGRAM_BOT_TOKEN` | Obligatoire, secret | Jeton du bot |
| `TELEGRAM_WEBHOOK_SECRET` | Obligatoire, secret | Secret vérifié sur le webhook |
| `TELEGRAM_CHAT_BL_ID` | Obligatoire | Groupe de dépôt des bons |
| `TELEGRAM_CHAT_SUPERVISION_ID` | Obligatoire | Canal de supervision (le groupe n'existe plus : voir §13.3) |
| `MISTRAL_API_KEY` | Obligatoire, secret | Clé de l'OCR Mistral |
| `COOKIE_SECURE` | Obligatoire | Attribut `Secure` du cookie de session |
| `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID` | Optionnelles | Drive ; sans elles, seule `drive-sync` refuse de démarrer |
| `CONTROLE_PRIX_ACTIF` | `false` | Réactive R07, R08, R09 |
| `CONTROLE_LIVRE_NON_FACTURE_ACTIF` | `false` | Réactive R06 |
| `API_DOCS_ACTIVES` | `false` | Sert `/docs`, `/redoc`, `/openapi.json` |
| `IA_ACTIVE` | `false` | Interrupteur général de l'IA |
| `OPENCODE_URL`, `OPENCODE_MOT_DE_PASSE` | Obligatoires si `IA_ACTIVE=true` | Accès au conteneur OpenCode |
| `IA_APPELS_MAX_JOUR` | 40, au moins 1 | Plafond quotidien d'appels à l'IA |

Les seuils, délais et interrupteurs modifiables à l'écran sont dans la table
`parametre` (écran Réglages) ; bornes et défauts dans
`app/modules/ingest/parametres.py`. Parmi eux : `tolerance_total_ht`,
`seuil_ressemblance_chantier_pct` (80), `delai_alias_non_resolu_h` (48),
`delai_chantier_silencieux_j` (7), `delai_ligne_bl_non_facturee_j` (45),
`duree_ignorance_j` (90), `prix_controle_bl_actif` et les réglages `prix_*`.
`delai_confirmation_bl_h` est masqué (R15 retirée).

### 9.2 Lues par Docker Compose et les scripts

`DOMAIN`, `ACME_EMAIL`, `API_HOST_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`, `DOCS_HOST_DIR`, `TEST_DATABASE_URL`, `RESTIC_REPOSITORY`,
`RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` (seulement si
le dépôt restic n'est pas un chemin local), `HABITAT_RENO_ENV_FILE`,
`COMPOSE_PROJECT_NAME`, `COMPOSE_OVERRIDE_FILE`. Fichier d'environnement de
production : `.env.prod`, jamais versionné. Modèle : `.env.example`.

Conteneur OpenCode (`deploy/opencode/`) : `OPENCODE_SERVER_PASSWORD`, et
`EXA_API_KEY` si besoin.

---

## 10. Démarrer en local, tests et qualité

Prérequis : Docker et Docker Compose, Python 3.11 avec `uv`, Node.js et `npm`.

```bash
uv sync                      # dépendances Python, dev comprises
npm --prefix web ci          # dépendances du front
cp .env.example .env && chmod 600 .env   # puis ajuster les valeurs locales
docker compose --env-file .env -f deploy/docker-compose.yml \
  -f deploy/docker-compose.dev.yml up -d postgres
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8450 --reload --reload-dir app
npm --prefix web run dev     # le proxy Vite relaie /api vers 127.0.0.1:8450
```

Premier administrateur :

```bash
uv run python -m app.cli utilisateur-creer \
  --email <adresse> --nom "Administrateur" --role admin --agence "Agence de test"
```

Le mot de passe est demandé deux fois, sans écho, 12 caractères au moins. Des
valeurs factices suffisent pour Telegram et Mistral tant qu'on ne lit pas de
document réel. Procédure complète : `docs/deploiement-et-tests.md`.

Tests et qualité :

```bash
uv run pytest                    # suite complète (PostgreSQL de dev requis)
uv run pytest -k <expression>    # tests ciblés
uv run pytest -m db              # tests qui exigent PostgreSQL
uv run ruff check && uv run ruff format --check
uv run mypy                      # strict, sur app/ et tests/
npm --prefix web run typecheck   # tsc --noEmit
npm --prefix web run build       # build Vite
```

- **3 115 tests au 04/11/2026.** Un test marqué `db` sans base échoue, il n'est
  jamais ignoré en silence. Le front n'a pas de tests unitaires : des tests
  « texte » en pytest (`tests/test_web_*.py`) lisent ses sources, en plus de `tsc`
  et `vite build`.
- Hooks pre-commit (`.pre-commit-config.yaml`) : ruff, mypy, suite pytest
  complète sous `flock /tmp/habitat_reno-tests.lock` (15 à 20 minutes), refus de
  tout fichier sous `tests/fixtures/` et de tout `.env`, typecheck et build du
  front, `pip-audit`, `npm audit`. Ils tiennent lieu d'intégration continue :
  **aucune CI n'est configurée sur GitHub**.
- Ne jamais utiliser `--no-verify`. Ne jamais lancer `pre-commit install` depuis
  un worktree (hooks partagés).
- Les fixtures (factures, photos de bons) sont des documents réels du client :
  ignorées par git, jamais dans un commit ni un journal. Les données de test sont
  inventées.

---

## 11. Commandes CLI

`python -m app.cli <commande>` ; en production,
`docker compose $P exec -T api python -m app.cli …` (sans `-T` pour une commande
interactive). Source : `app/cli.py` (19 commandes). Les commandes qui réécrivent
des bons ont un `--simulation` : toujours l'utiliser d'abord.

| Commande | Rôle |
| --- | --- |
| `bl-non-recus <facture.pdf>` | Liste les blocs BL d'une facture avec l'indicateur « photo reçue » (lecture seule) |
| `utilisateur-creer --email --nom --role {admin,agent} --agence [--telegram-id]` | Crée un compte (mot de passe saisi de façon interactive) |
| `utilisateur-desactiver --email` | Désactive un compte |
| `fournisseur-definir --nom [--siret] [--tva] [--alias …] [--agence …]` | Crée ou met à jour un fournisseur (jamais créé automatiquement) |
| `fournisseur-fusionner --source NOM --cible NOM [--simulation]` | Fusionne un fournisseur dans un autre : bons, noms de chantier appris, articles, agences, grilles et historique passent à la cible, nom et alias de la source deviennent des alias de la cible, puis la source est supprimée. Une seule transaction, journalisée. Refus si les deux fournisseurs ont un document de même numéro |
| `resoudre-fournisseurs [--simulation]` | Rattache aux fournisseurs créés après coup les bons déjà reçus, sans rappeler l'OCR ; ignore les bons corrigés ou validés à la main ; un bon sans motif restant passe à « reçu » |
| `recalculer-bons [--simulation]` | Applique aux bons « à vérifier » les règles de lecture du §5 à partir de la lecture déjà gardée, sans rappeler l'OCR ; ignore les bons corrigés ou validés à la main |
| `importer-historique-prix --fournisseur NOM --fichier X.xlsx --feuille F --source TEXTE [--simulation]` | Range les prix d'une feuille d'historique dans `prix_observe` (jamais dans la grille) ; idempotente |
| `rapprocher --facture <uuid>` ou `--tout` | Rejoue le rapprochement (idempotent) |
| `controles-differes` | Évalue les règles de suivi R14, R16 (et R06 si elle est activée) |
| `controler-prix [--depuis AAAA-MM-JJ]` | Recontrôle les prix des bons non archivés depuis une date (1er du mois précédent par défaut) |
| `rattacher-chantiers` | Reprise des noms de chantier en attente et des bons sans chantier (idempotente, à lancer au déploiement d'un changement de rattachement) |
| `chantiers-alias-suspects` | Liste, en lecture seule, les noms appris dont les nombres diffèrent de ceux du chantier. Diagnostic manuel : la sortie contient des noms de chantier, ne pas la copier ni la planifier |
| `ranger-photos` | (Re)construit le rangement des photos sous `bl/<AAAA>/<MM>/…` (idempotente) |
| `drive-sync [--limite 1..1000]` | Synchronise les documents en attente vers Google Drive (bloquée, jamais exécutée en réel) |
| `rapport-ocr <dossier> --sortie <md> [--seuil] [--appeler-ocr]` | Mesure le taux d'erreur OCR sur des photos annotées (`docs/protocole-mesure-ocr.md`) |
| `synthese-commentaires [--semaine AAAA-MM-JJ]` | Synthèse hebdomadaire des commentaires par l'IA (sans effet IA éteinte) |
| `ia-prix` | Explique les alertes de prix et cherche un prix internet (sans effet IA éteinte) |
| `essai-prix-internet --fichier <csv>` | Essai manuel de la recherche de prix sur des produits réels, rien n'est enregistré |

---

## 12. Déploiement et retour arrière

### 12.1 Hébergement

Le serveur actuel est un VPS OVH du prestataire, **provisoire**, partagé avec
d'autres projets : nginx (certbot) remplace Traefik. La cible reste un serveur
dédié au nom du client, où seul Ilane aura un compte (décision du client, §2.4).

Production : projet Compose `habitat_prod`, fichiers `deploy/docker-compose.yml`
+ `deploy/docker-compose.vps.yml`, environnement `.env.prod` (non versionné), API
sur `127.0.0.1:8450`, image `habitat_prod-api`. Autres fichiers :
`deploy/docker-compose.dev.yml` (PostgreSQL de développement),
`deploy/docker-compose.ia.yml` (surcouche IA), `deploy/opencode/` (conteneur
OpenCode), `deploy/nginx/habitat.conf` (vhost, limites de débit, en-têtes).

### 12.2 Déploiement tel qu'il se pratique

Uniquement **sur le GO d'Ilane**, depuis l'arbre dédié `~/habitat_reno-prod`,
détaché sur le commit à déployer.

```bash
cd ~/habitat_reno-prod
git switch --detach <commit à déployer>
P="-p habitat_prod --env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"

# 1. Sauvegarde de la base, dans ~/sauvegardes-habitat/ (fichier protégé, hors dépôt)
(umask 077; docker compose $P exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > ~/sauvegardes-habitat/avant-<lot>-prod-$(date +%Y%m%d-%H%M).dump)

# 2. Image actuelle gardée sous un nom stable (retour arrière du code)
docker tag habitat_prod-api:latest habitat_prod-api:avant-<lot>

# 3. Build de l'API
docker compose $P build api

# 4. Seulement s'il y a une migration : arrêt de l'API, puis migration
docker compose $P stop api
docker compose $P run --rm -T api alembic upgrade head

# 5. Démarrage et attente de l'état sain
docker compose $P up -d --wait api

# 6. Contrôles : /health, révision, journaux, un parcours dans l'application
docker compose $P exec -T api alembic current
docker compose $P logs --tail 100 api
```

Puis, selon le lot, les commandes du §11 (par exemple `recalculer-bons` après un
changement des règles de lecture), toujours `--simulation` d'abord. Si l'IA est
allumée, ajouter `-f deploy/docker-compose.ia.yml` à `$P`, sinon l'API perd l'IA
sans message.

### 12.3 Passage de `dev` vers `main`

Seulement avec l'accord d'Ilane, par une PR avec commit de fusion, puis une
étiquette `mise-en-prod-AAAA-MM-JJ` sur ce commit. Étiquettes existantes : `lot-1`
à `lot-5`, `refonte-front`, `mise-en-prod-octobre-2026`,
`mise-en-prod-2026-09-30`, `mise-en-prod-2026-10-01`, `mise-en-prod-2026-10-22`,
`mise-en-prod-2026-11-02`.

### 12.4 Retour arrière

Ne jamais lancer `alembic downgrade`. Deux cas.

- **Schéma inchangé par le lot** (pas de migration) : remettre l'image
  précédente (`docker tag habitat_prod-api:avant-<lot> habitat_prod-api:latest`,
  puis `docker compose $P up -d --no-build api`) et revenir au commit précédent
  dans l'arbre de déploiement.
- **Migration appliquée** : restaurer ensemble code, base et documents. Soit le
  dump pris à l'étape 1 (base vide puis `pg_restore`, puis image `avant-<lot>`),
  soit une restauration complète depuis un instantané restic avec
  `deploy/restore.sh <identifiant-snapshot> --confirmer`. Tout dépôt reçu depuis
  le déploiement est perdu par la restauration : prévenir d'abord.

Images et dumps de retour arrière des lots du 31/10 au 02/11/2026 :
`habitat_prod-api:avant-2026-10-31`, `:avant-lot2-2026-11-01`,
`:avant-lot3-2026-11-02`, `:avant-lot4-2026-11-02` ; dumps
`~/sauvegardes-habitat/avant-lot{1,2,3,4}-prod-*.dump`.

Procédures complètes : `deploy/RESTAURATION.md`, `docs/deploiement-et-tests.md`
§11, `docs/deploiement-octobre-2026.md` §7. Historique des déploiements :
archive §17.

---

## 13. Exploitation

### 13.1 Sauvegardes

- `deploy/backup.sh` : `pg_dump -Fc` puis `restic backup` du dump et des
  originaux (`DOCS_HOST_DIR`) ; rétention de 30 sauvegardes quotidiennes et 12
  mensuelles.
- Les dépôts restic sont **locaux** (`~/sauvegardes-habitat/`, même serveur) :
  ils protègent d'une erreur applicative, **pas de la perte du serveur**.
  Sauvegardes hors du serveur : décision du client. Les mots de passe restic
  doivent être gardés par Ilane : sans eux, les sauvegardes sont illisibles.
- **Restauration prouvée par un essai réel le 30/09/2026**
  (`deploy/test-restauration.sh` : comptes de lignes et empreintes des documents
  identiques, `/health` à 200). `deploy/restore.sh` fait tous ses contrôles avant
  la première destruction et garde une copie de sécurité de la base courante
  (jamais purgée, à supprimer à la main après validation).
- Procédure complète : `deploy/RESTAURATION.md`.

### 13.2 Tâches planifiées

Minuteries systemd utilisateur (le paquet `cron` n'est pas installé), posées par
`deploy/installer-taches.sh prod [--taches liste]`. Heures de Paris. Chaque
tâche a `OnFailure=` vers `deploy/alerte-echec.sh`.

| Tâche | Commande | Heure (production) | Posée par défaut |
| --- | --- | --- | --- |
| `photos` | `ranger-photos` | 02:30 | Oui |
| `sauvegarde` | `deploy/backup.sh` | 03:00 | Oui (exige les variables restic) |
| `controles` | `controles-differes` | 06:15 | Oui |
| `synthese` | `synthese-commentaires` | 07:00 | Non (IA) |
| `ia-prix` | `ia-prix` | chaque heure de 07:10 à 20:10 | Non (IA) |

Les trois tâches par défaut sont posées en production depuis le 28/09/2026.
Vérifié le 04/11/2026 (`systemctl --user list-timers 'habitat-*'`) : toutes
trois ont réussi la nuit du 03 au 04/11. Sans supervision (§13.3), ce contrôle
se fait à la main. Le script connaît encore l'instance
`demo` : sans objet depuis le 29/10/2026. La synchronisation Drive n'est pas
planifiée.

### 13.3 Supervision : absente

Le groupe Telegram de supervision a été **supprimé le 28/09/2026** (décision
d'Ilane). Conséquences :

- **Aucune alerte ne sort du serveur** : ni échec d'une tâche planifiée, ni
  sauvegarde manquante, ni expéditeur refusé. Les messages de supervision que
  l'application tente d'envoyer échouent et ne sont que journalisés.
- Aucune sonde externe ; `GET /health` ne vérifie que la base (ni la révision
  Alembic, ni Telegram, ni Mistral).
- Les scripts de supervision de la branche `feature/exploitation-2` (27/09 :
  surveillance du site et du disque, vérification hebdomadaire des sauvegardes,
  remontée d'un échec du rangement des photos) **ne sont pas commités** et restent
  dans l'arbre principal `~/habitat_reno`. Ils répondraient au constat F-04
  (aucune alerte si une sauvegarde ne s'exécute pas), toujours ouvert.
- Pour rétablir une alerte : Ilane ouvre une conversation privée avec le bot,
  renseigne son identifiant dans `TELEGRAM_CHAT_SUPERVISION_ID`, puis l'API est
  recréée.

### 13.4 Journaux et contrôles à la main

```bash
P="-p habitat_prod --env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"
docker compose $P ps && docker compose $P logs --tail 200 api
systemctl --user list-timers 'habitat-*'
journalctl --user -u habitat-prod-sauvegarde.service -n 50
```

Les sorties des tâches vont dans journald (taille plafonnée). L'écran Journal
trace chaque action d'un compte.

---

## 14. Sécurité et RGPD

Court ; détail et constats de l'audit : archive §19 et §20.

- **Authentification** : cookie httpOnly, session en base (12 h glissantes),
  argon2, limitation de `/login` (slowapi et zone nginx `login`). Pas de JWT,
  rien dans `localStorage`, même origine, contrôle d'origine anti-CSRF.
- **Fichiers Telegram** : signature vérifiée avant toute écriture, taille
  plafonnée ; documents en 0640 (dossiers 0750).
- **Conteneurs durcis** (`no-new-privileges`, `pids_limit`, `cap_drop: ALL` sur
  l'API) ; `/docs`, `/redoc`, `/openapi.json` fermés par défaut ; en-têtes et
  limites de débit nginx (`deploy/nginx/habitat.conf`).
- **Secrets** en `SecretStr` (absents des journaux), sauf `DATABASE_URL` ;
  `.env*` et `tests/fixtures/` refusés par les hooks.
- **Sous-traitants** : Mistral (OCR, Union européenne), Telegram (hors Union
  européenne), OVH (hébergement) ; OpenAI et Exa seulement si l'IA est allumée ;
  Google Drive prévu, bloqué.
- **Clés et mot de passe affichés en septembre** dans des échanges de travail
  (Mistral, Telegram, Google, mot de passe admin) : changés par Ilane (confirmé
  le 04/11/2026).
- **Reste à faire** : registre des traitements et information des salariés.

---

## 15. IA

**Éteinte en production (`IA_ACTIVE=false`) et gelée par Ilane depuis le
29/09/2026** : aucune évolution de l'IA sans son accord. Le code est livré et
testé ; rien ne l'appelle tant que l'interrupteur est éteint.

Ce qu'elle ferait, une fois allumée (un conteneur OpenCode séparé, relié au
compte ChatGPT d'Ilane, modèle `gpt-5.6-sol`, recherche web par Exa) :

- une **synthèse hebdomadaire** des commentaires de lignes, avec des actions à
  cocher, sur la Vue d'ensemble, mention « Rédigé par l'IA — à vérifier » ;
- l'**explication des alertes de prix** (jamais un nouveau chiffre : l'écart est
  déjà calculé par les règles) ;
- la **recherche d'un prix public sur internet**, à titre indicatif, avec ses
  sources, pour les produits absents de toute référence interne.

L'IA ne décide jamais : elle explique, résume ou cherche, un humain tranche.
Plafond quotidien d'appels : `IA_APPELS_MAX_JOUR`. Le Laboratoire IA (`/ia`)
permet d'essayer les usages sans rien enregistrer.

Guide opérationnel (installation, allumage, surveillance, arrêt d'urgence) :
`docs/phase-4-ia.md`. Conception et décisions : archive §12 et
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`. Ce qui partirait chez
les sous-traitants de l'IA, et l'avenant du cahier des charges §15 (rédigé, « à
confirmer ») : archive §19.2.

---

## 16. Organisation du travail

- **`main` = ce qui est en production**, sans commit direct. `dev` est la
  branche d'intégration.
- Chaque lot : branche `feature/…` partie de `dev`, **PR vers `dev`** fusionnée
  par Ilane. `dev` vers `main` par une PR avec commit de fusion, **seulement avec
  l'accord d'Ilane**, puis étiquette `mise-en-prod-AAAA-MM-JJ` (§12.3). Rien en
  production sans son GO.
- **Une tâche = un commit**, message en français préfixé du module (ex.
  `extract: parseur Unikalo, blocs BL et lignes`). Tests avant ou avec le code ;
  `pytest`, `ruff` et `mypy` passent avant chaque commit.
- **Hooks et verrou** : la suite complète tourne à chaque commit sous
  `flock /tmp/habitat_reno-tests.lock`, pour que deux sessions ne lancent pas deux
  suites ou deux builds en même temps (mémoire du serveur).
- **Plusieurs sessions Claude Code en parallèle**, chacune dans son worktree, avec
  une base de test distincte sur le même PostgreSQL de développement. Arbre dédié
  aux déploiements : `~/habitat_reno-prod`.
- Numéros réservés (migrations, règles, réglages, routes) :
  `docs/roadmap-octobre-2026.md` §2.4. Prochaine migration : `0019`.
- Simplicité : si une solution trois fois plus simple couvre 80 % du besoin, on la
  prend et on note ce qu'elle ne couvre pas dans `docs/dette.md`.

---

## 17. Historique en bref

Le détail (lot par lot, les 24 premières PR, le déroulé jour par jour) est dans
l'archive §3.1 et §22.

| Étape | Dates | Contenu |
| --- | --- | --- |
| Lots 1 à 5 | 16–20/09/2026 | Socle, collecte, extraction, rapprochement (R01 à R17), restitution |
| Déploiement VPS, refonte du front | 23/09 | Cinq écrans, navigation téléphone |
| Désactivations, optimisations | 24–25/09 | R06 à R09 désactivées ; `/docs` fermés ; sécurité et rapidité |
| Phases 1 à 4 | 27–28/09 | Rattachement des chantiers, R18, comptes ; commentaires ; lot Prix (R19 à R25) ; IA (éteinte en production) ; sauvegardes locales ; mise en production du 28/09 ; groupe de supervision supprimé |
| Gel de l'IA, audit | 29/09 | IA gelée ; audit complet |
| Corrections de l'audit | 29–30/09 | 13 constats importants ; restauration essayée pour de vrai ; mise en production du 30/09 |
| Contestations de prix, comptes automatiques, photos en rafale | 01/10–22/10 | Migration `0016` ; PR #19 à #24 ; mises en production du 01/10 et du 22/10 |
| Ménage de la démonstration | 29/10 | Démo supprimée |
| PR #26 (lot 1) | 31/10 | R15 retirée (`0017`) ; `resoudre-fournisseurs` |
| PR #27 (lot 2) | 31/10–01/11 | Règles de lecture (§5), `recalculer-bons`, bons dans les livraisons, archivage d'une facture, historique d'un produit (`0018`) |
| PR #28 (lot 3) | 02/11 | Montant d'un bon, suivi des chantiers du mois, carte « Factures » |
| PR #29 (lot 4) | 02/11 | `fournisseur-fusionner`, prénoms d'employés retirés du nom de chantier ; déployée le 02/11 à 22 h 27 UTC |
| PR #30 et #31 | 04/11 | `dev` vers `main` (étiquette `mise-en-prod-2026-11-02`) ; hôte de démonstration retiré du vhost nginx |

---

## 18. Limites connues et ce qui attend le client

### 18.1 Fonctionnel et exploitation

- **Factures** : seul le format **Unikalo** est lu. Aucune facture Point.P reçue :
  pas de lecteur Point.P, donc **aucun rapprochement avec Point.P**. Les factures
  d'octobre sont attendues (demandées le 04/11/2026). Une facture « à vérifier » ne
  se corrige pas depuis l'application (écran proposé, non construit).
- **Mesure de l'OCR** : taux d'erreur jamais mesuré selon
  `docs/protocole-mesure-ocr.md`. Des photos réelles arrivent en production
  depuis octobre, mais aucune n'est annotée pour la mesure.
- **Prix** : contrôle à la réception du bon seulement, pas à la facture. R06 à R09
  désactivées. Verdicts de rapprochement de la facture d'août et quatre montants du
  Bilan : non confirmés par le client. R22 est levée pour chaque ligne d'un
  fournisseur sans grille (proposition d'Ilane en attente, §2.5).
- **Règle « semi-remorque »** : jamais construite. **Google Drive** : bloqué (il
  faut un Drive partagé Google Workspace ou l'accès OAuth) ; les photos sont rangées
  sur le serveur en attendant, ce qui n'est pas une sauvegarde.
- **Lots du 31/10 au 02/11** (`docs/dette.md`) : une référence de commande
  inconnue laisse le bon sans chantier ; un mot de liaison est toujours retiré du
  nom de chantier lu ; la légende n'est pas nettoyée des prénoms ; la fusion de
  fournisseurs n'a pas d'écran ; une facture archivée par erreur ne se rétablit
  pas ; une ligne remisée peut échouer le contrôle quantité × prix.
- **Employés** : ils ne voient que leurs propres dépôts (hypothèse non confirmée).
- **Serveur provisoire**, partagé avec d'autres projets ; à la bascule vers le
  serveur dédié : reproduire les limites de débit et de taille, poser des limites
  de mémoire, revoir les droits des documents.
- **Sauvegardes locales** seulement ; **aucune alerte ne sort du serveur** (§13.3,
  F-04 ouvert) ; pas de sonde externe, pas de CI GitHub, pas de `deploy.sh`.
- **Compte ChatGPT personnel** pour l'IA : sur un serveur dédié, prévoir un compte
  ou une clé au nom du client.

### 18.2 Ce que le client doit fournir ou valider

| Élément | Situation au 04/11/2026 |
| --- | --- |
| Factures fournisseurs d'octobre en PDF | Demandées le 04/11 |
| Au moins une facture Point.P | Non reçue |
| 30 photos de BL réelles annotées, dont 10 dégradées (mesure de l'OCR) | Photos reçues en production depuis octobre ; aucune annotée |
| Compte OVH et serveur dédié | Décision du client |
| Accès Google Drive (Drive partagé ou OAuth) | Non fourni |
| Confirmation des verdicts d'août, des quatre montants, du classement d'août, de « Conforme » strict | À faire |
| Acceptation de la refonte des écrans (écart au cahier des charges §4.6) | À faire |
| Avenant IA (§15) | « À confirmer » |
| Registre des traitements, information des salariés | Non fait |
| Disponibilité pour la recette (lot 6 : recette sur deux mois, formation, procès-verbal) | Lot 6 non commencé |

Évolutions proposées, non construites : `docs/evolutions-proposees.md`.

---

## 19. Index de la documentation

| Fichier | Contenu |
| --- | --- |
| `CLAUDE.md` | Consignes de travail : stack imposée, frontières, méthode, état du projet |
| `ARCHITECTURE.md` | Schémas : conteneurs, modules, modèle de données, flux, cycles de vie, front, règles |
| `docs/readme-octobre-2026.md` | Ancien README (état au 22/10/2026, 25 sections) : IA (§12), sécurité et RGPD (§19), audit du 29/09 (§20), historique et PR #1 à #24 (§22), limites (§23), glossaire (§25) |
| `docs/cahier-des-charges.md` | Cahier des charges, fait foi ; avenants §14 et §15 |
| `docs/roadmap-octobre-2026.md` | Demandes d'octobre, décisions d'Ilane (§1.2), organisation git (§2) |
| `docs/dette.md` | Dette technique, simplifications assumées, limites de chaque lot |
| `docs/phase-4-ia.md` | Guide opérationnel de l'IA |
| `docs/deploiement-et-tests.md`, `docs/deploiement-octobre-2026.md`, `docs/deploiement-corrections-audit.md` | Tests, déploiement, retour arrière (§11 du premier) ; procédures d'octobre et des corrections de l'audit |
| `docs/lot-N-recette.md`, `docs/plan-lot-N.md` (N = 1 à 5), `docs/mise-en-production-1er-octobre-recette.md`, `docs/phase-2-exploitation-recette.md`, `docs/refonte-front-recette.md` | Recettes et plans des lots, recettes des phases 1 et 2 et de la refonte |
| `docs/passation-lots-1-2.md`, `docs/passation-lot-3.md` à `docs/passation-lot-5.md`, `docs/exploitation-lot-4.md`, `docs/exploitation-lot-5.md` | Passations entre sessions ; contrôles différés, rejeu, Drive |
| `docs/protocole-mesure-ocr.md`, `docs/evolutions-proposees.md` | Mesure du taux d'erreur OCR ; évolutions hors cahier des charges |
| `docs/superpowers/specs/`, `docs/superpowers/plans/` | Conceptions et plans d'exécution (refonte du front, commentaires, phase 1, prix, IA, prix internet, contestations) |
| `infra/README.md` | Documentation technique d'ensemble (état du 24/09/2026) |
| `deploy/` | `RESTAURATION.md`, scripts de sauvegarde, de restauration et de tâches planifiées, piles Compose, vhost nginx, conteneur OpenCode |
