# Refonte du front — conception validée (23/09/2026)

Maquettes de référence (privées, compte d'Ilane) :
https://claude.ai/artifact/VwiXWPUt4Vg8uQULB8BrLG — artboards `Main` (vue
d'ensemble, direction A retenue), `ARegler`, `FicheChantier`, `BL`. La
direction B (`Tuiles`) est écartée.

## 1. Pourquoi

L'interface actuelle (14 écrans, organisés par objet technique : factures,
documents, anomalies, bilan…) n'est pas présentable au client ni utilisable
par une personne non technique. Démo client le **samedi 26/09/2026**.

Intention validée avec Ilane :

- utilisateur principal : **le dirigeant, au bureau sur ordinateur et en
  déplacement sur téléphone** (précisé par Ilane le 23/09) ;
- en 5 secondes il doit voir **la santé de chaque chantier (et de son client
  final)** et **l'argent à vérifier** ;
- **refonte complète** des écrans, pas seulement un habillage ;
- professionnel, sobre, sans jargon (aucun code de règle, « bloc », « alias »
  ou « rapprochement » visible) ; « faut pas trop compliquer la chose ».

Hypothèses (non dites par Ilane, à corriger si fausses) : les agents terrain
continuent de passer par Telegram et n'ont besoin que des écrans « Documents »
(leurs dépôts) et du détail d'un BL.

**Téléphone = cible à part entière** : chaque écran a une présentation 375 px
pensée pour le dirigeant (tuiles en grille 2×3, tableaux transformés en
cartes empilées, panneau de détail d'« À régler » en page plein écran,
barre latérale remplacée par une barre de navigation en bas avec les cinq
entrées). La démo doit pouvoir se faire sur téléphone.

## 2. Direction visuelle (A — « Registre »)

- Fond ivoire `#f6f4ef`, surfaces blanches, bordures `#e3dfd5`, rayon 14 px.
- Accent vert profond `#1f4d3a` (navigation active, actions principales).
- États : conforme `#2f7a55`, écart `#c77700` (texte `#a86400`/`#7a4a00`),
  sans bon / urgent `#b3261e`. Toujours doublés d'un libellé (jamais la
  couleur seule).
- Typographies : **Fraunces** (titres et grands chiffres), **IBM Plex Sans**
  (texte), **IBM Plex Mono** (montants, numéros). **Auto-hébergées** via les
  paquets `@fontsource/*` : la CSP (`default-src 'self'`) interdit Google Fonts.
- Montants au format français (`1 310,00 €`), dates `12/09/2026`.
- Jetons dans `tailwind.config` (`theme.extend`), composants de base partagés
  dans `web/src/ui/` (Carte, Chiffre, Pastille d'état, Tableau, Bouton,
  Filtres, Fil d'Ariane, Barre latérale).

## 3. Navigation (5 entrées + 2 discrètes)

| Entrée | Route | Remplace | Rôle |
| --- | --- | --- | --- |
| Vue d'ensemble | `/` | (nouveau) | admin |
| À régler | `/a-regler` | `/a-traiter`, `/anomalies` | admin |
| Chantiers | `/chantiers`, `/chantiers/:id` | `/bilan`, `/bilan/:chantierId…`, `/chantiers` | admin |
| Fournisseurs | `/fournisseurs`, `/fournisseurs/:id` | `/bilan/fournisseurs…` | admin |
| Documents | `/documents`, `/documents/:id`, `/bl/:id` | `/factures`, `/factures/:id`, `/bl`, `/documents/:id` | admin + agent |
| Réglages, Journal (bas de barre) | `/reglages`, `/journal` | inchangées | admin |

Les anciennes URL redirigent vers les nouvelles (liens déjà envoyés par
Telegram). Aucune fonctionnalité existante n'est supprimée : elles sont
regroupées.

## 4. Écrans

**Vue d'ensemble** (maquette `Main`) — sélecteur de mois, bouton « Exporter
pour Excel » (export détaillé existant) ; six tuiles : Facturé, Conforme,
Écart prix ou quantité, Sans bon de livraison, Problèmes à régler (dont
urgents), BL reçus / facturés ; tableau des chantiers (nom, client, agence,
pastille d'état, facturé, à vérifier, nombre de problèmes), trié par montant
à vérifier ; colonne « À régler en priorité » (4 premiers problèmes).

**À régler** (maquette `ARegler`) — liste unique des anomalies ouvertes et
des documents/alias à traiter, en langage courant, filtres (Tous, Urgents,
BL manquants, Prix, Quantités, À rattacher, Déjà réglés) ; panneau de détail
« Pourquoi c'est signalé » avec les valeurs chiffrées de `detail`, liens
facture et BL, commentaire obligatoire, boutons « Contesté auprès du
fournisseur » (= traitée) et « C'est normal, ignorer » (= ignorée). Les
documents « à vérifier » et alias en attente y apparaissent comme problèmes
du type « Bon illisible à corriger » / « Chantier à rattacher », avec leur
action existante (correction, validation d'alias).

**Chantiers** — liste (même tableau que la vue d'ensemble, tous mois ou mois
choisi, création de chantier, filtre agence) ; **fiche chantier** (maquette
`FicheChantier`) : client, agence, dernier dépôt, pastille d'état, quatre
chiffres, tableau des livraisons (clic → page BL), problèmes ouverts, export,
édition nom/client/agence/actif et alias (reprise de l'écran actuel).

**Page BL** (maquette `BL`) — aperçu de la photo, **Télécharger la photo**,
Ouvrir en grand, déposant, canal et heure, quantités vérifiées ; tableau
livré / facturé / prix / contrôle par ligne ; lien facture ; « Régler les
problèmes » ; « Corriger la lecture du bon » (correction existante).

**Fournisseurs** — liste avec les quatre chiffres et le nombre de problèmes ;
fiche fournisseur : chantiers concernés, factures, problèmes.

**Documents** — liste unique filtrable (Factures / Bons de livraison, mois,
chantier, fournisseur, « à vérifier ») ; dépôt d'une facture PDF ; détail
facture (blocs présentés comme « livraisons ») ; l'agent n'y voit que ses
dépôts, comme aujourd'hui.

**Réglages, Journal, Connexion** — même contenu, nouvel habillage, libellés
en français courant.

## 5. Langage courant

Un seul module de présentation `web/src/ui/libelles.ts` associe chaque code
de règle à un titre et construit la phrase à partir des valeurs de `detail`
déjà calculées par le serveur (aucun calcul métier côté front) :

| Règle | Titre affiché |
| --- | --- |
| R01 | Bon de livraison jamais reçu |
| R02 | Livré sans bon |
| R03 | Facturé plus que livré |
| R04 | Facturé moins que livré |
| R05 | Facturé mais absent du bon |
| R06 | Livré mais pas facturé |
| R07 | Prix un peu plus cher |
| R08 | Prix plus cher que d'habitude |
| R09 | Remise habituelle oubliée |
| R10 | Erreur de calcul sur la facture |
| R11 | Erreur de calcul sur le bon |
| R12 | Bon facturé deux fois |
| R13 | Avoir sans achat d'origine |
| R14 | Chantier à rattacher |
| R15 | Quantités non confirmées par l'équipe |
| R16 | Chantier sans bon déposé depuis 7 jours |
| R17 | Quantité inhabituelle pour le conditionnement |

Gravité : haute → « Urgent », moyenne → « À voir », basse → « Info ».

## 6. Serveur (ajouts limités, règles de frontière inchangées)

1. **Client du chantier** — colonne `chantier.client` (texte libre,
   nullable), migration `0010`, lecture/écriture par les routes chantiers
   existantes. **Hors cahier des charges** : ajout demandé par Ilane le
   23/09, à signaler au client comme évolution (CDC §11 « demandes hors
   périmètre »). Version minimale, sur le modèle de `agence`.
2. **Tableau de bord** — `ingest/tableau_de_bord.py` +
   `GET /api/tableau-de-bord?mois=` (admin) : totaux du mois (les quatre
   montants existants de `bilan.py` + `conforme = rapproché − en écart`),
   problèmes ouverts et urgents, BL reçus / BL facturés, lignes chantier du
   bilan enrichies du client et d'un **état** calculé côté serveur
   (`conforme`, `bl_manquant`, `prix`, `quantites`, `a_rattacher`) et les
   problèmes prioritaires (tri : gravité puis montant en jeu). Réutilise les
   agrégats de `bilan.py`, jamais un second calcul divergent.
3. **Téléchargement** — `GET /api/documents/{id}/fichier?telechargement=1`
   ajoute `Content-Disposition: attachment` avec un nom explicite
   (`BL_<numero>_<chantier>.jpg`).
4. **Page BL** — si aucune route existante ne renvoie, pour un BL, ses lignes
   avec la quantité et le prix facturés appariés et le contrôle de chaque
   ligne, l'ajouter dans `ingest` (lecture seule, à partir de
   `rapprochement_ligne` et des anomalies de ligne).

Chaque ajout : tests service (base de test), route (admin/agent), types
openapi régénérés.

## 7. Contraintes

Stack inchangée (React 18, Vite, React Router, TanStack Query, Tailwind
`extend`, types openapi-typescript). Aucune nouvelle bibliothèque d'interface
hors `@fontsource/*`. Pas de logique métier dans le front. Les tests
existants (`tests/test_web_*.py`, contrats front) sont mis à jour avec les
routes. Accessibilité : vrais `<button>`/`<a>`/`<label>`, contraste 4,5:1,
cibles ≥ 44 px. Largeurs vérifiées : 1440, 1280 et 375 px ; la présentation téléphone fait
partie de l'acceptation de chaque écran, pas d'une passe finale.

## 8. Découpage et calendrier (démo samedi 26/09)

1. Mercredi–jeudi : socle (jetons, polices, composants `ui/`, barre latérale,
   routes et redirections) + ajouts serveur 1 à 3.
2. Jeudi–vendredi, en parallèle : Vue d'ensemble ; À régler ; Chantiers +
   fiche + page BL (+ ajout serveur 4) ; Fournisseurs ; Documents ; Réglages,
   Journal, Connexion.
3. Vendredi soir : revue d'ensemble, recette navigateur sur la démo et la
   production, déploiement des deux instances.

Si le temps manque, priorité à la démo : Vue d'ensemble, À régler, fiche
chantier, page BL ; les autres écrans gardent au minimum le nouvel habillage
(socle) sans refonte de contenu. Ilane est prévenu avant de couper.

## 9. Hors périmètre

Nouvelles règles, notifications, rôle « client final » avec accès, Drive
(bloqué par l'absence de Drive partagé), refonte de l'expérience Telegram.
