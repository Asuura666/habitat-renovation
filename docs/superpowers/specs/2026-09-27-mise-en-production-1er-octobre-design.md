# Mise en production du 1er octobre — conception validée (27/09/2026)

Demandes de la réunion client rapportées par Ilane le 27/09/2026 (points 1
et 2 de la liste d'octobre), plus deux demandes d'Ilane le même jour :
gestion des comptes par un admin et photos rangées sur le serveur. Le lot
Prix (grilles, contrôle des prix au BL, page de suivi) et les commentaires
feront chacun l'objet d'une spec séparée. Avenant correspondant :
`docs/cahier-des-charges.md` §14.

## 1. Pourquoi

Le client met l'application en production le **1er octobre 2026** pour
suivre les BL du mois et les rapprocher des factures. La production n'a
aujourd'hui aucun chantier et un seul compte. Les employés vont envoyer
leurs photos dès le 1er : les bons doivent se ranger seuls dans leur
chantier, sans que personne ne crée les chantiers à l'avance.

Décisions d'Ilane (27/09) :

- nom du chantier lu sur le BL + nom tapé par l'employé en **légende de la
  photo** Telegram (confirmation) ;
- ressemblance **≥ 90 %** (réglable dans Réglages) avec un chantier
  existant → rattaché ; sinon **chantier créé automatiquement**, « à
  compléter » (sans agence ni client), signalé sur le site ;
- nom lu et légende qui désignent deux chantiers différents → **alerte,
  l'humain décide** ;
- bouton « Fusionner avec… » contre les doublons ;
- pas d'import de la liste des chantiers : le client complétera lui-même ;
- une seule règle pour les bons et les factures ;
- « Supprimer » un compte = retirer l'accès (le nom reste sur les bons) ;
- photos rangées dans `bl/<année>/<mois>/`, nommées avec le **jour du
  dépôt**, le déposant et le chantier.

## 2. Identification des chantiers

### 2.1 Les deux sources

- **Nom lu** : `chantier_brut` extrait du bon (OCR), décomposé par
  `normalize.chantier.decomposer_chantier` (préfixe « chantier » et code
  final entre parenthèses retirés, forme normalisée).
- **Légende** : `message.caption` d'une photo ou d'un fichier Telegram,
  lue par `messaging.telegram.lire_update`, conservée telle quelle sur le
  document (`document.legende`, texte, 200 caractères au plus), décomposée
  de la même façon. Affichée sur la page du bon (« Chantier indiqué par
  l'employé »). Le bot continue d'ignorer les messages texte seuls.

### 2.2 Ressemblance (module pur `normalize`)

`ressemblance(a, b) -> Decimal` : les deux libellés passent par
`normaliser_libelle` (casse, accents, ponctuation), leurs mots sont triés
(l'ordre des mots ne compte pas), puis `difflib.SequenceMatcher.ratio()`
× 100, arrondi à l'entier inférieur. Aucune nouvelle dépendance.

Un chantier a plusieurs noms : son `nom_canonique` et les libellés de ses
alias (tous fournisseurs confondus). Son score pour un libellé est le
meilleur score de ses noms. Un chantier fusionné compte pour le chantier
dans lequel il a été fusionné (ses noms restent des noms de la cible).

`reconnaitre_chantier(libelle, noms, seuil) -> Correspondance` (pur) :

- libellé vide → `vide` ;
- meilleur score < seuil → `inconnu` ;
- un seul chantier au meilleur score (≥ seuil) → `reconnu(chantier_id,
  score)` ;
- plusieurs chantiers **différents** à égalité au meilleur score →
  `ambigu(candidats)`.

Avant toute ressemblance, un alias **exact** du même fournisseur
(`(fournisseur_id, libellé normalisé)`) déjà rattaché donne `reconnu`
(score 100, méthode « nom connu ») : comportement actuel conservé.

Seuil : paramètre `seuil_ressemblance_chantier_pct`, « Ressemblance
minimale d'un nom de chantier », %, défaut 90, bornes 50–100.

### 2.3 Table de décision (fonction pure `decider_chantier`)

| Nom lu | Légende | Décision |
| --- | --- | --- |
| reconnu A | vide, inconnue, ou reconnue A | **rattacher A** |
| reconnu A | ambiguë, A parmi les candidats | **rattacher A** |
| reconnu A | reconnue B ≠ A, ou ambiguë sans A | **alerte** (candidats A, B…) |
| ambigu | quelle qu'elle soit | **alerte** (candidats du nom lu, plus B si la légende est reconnue) |
| inconnu | reconnue B | **rattacher B** et apprendre le nom lu comme autre nom de B |
| inconnu | vide ou inconnue | **créer** un chantier avec le nom lu |
| inconnu | ambiguë | **alerte** (candidats de la légende) |
| vide | reconnue B | **rattacher B** |
| vide | inconnue | **créer** un chantier avec la légende |
| vide | ambiguë | **alerte** |
| vide | vide | aucun chantier (comme aujourd'hui) |

- **Apprentissage** : dès qu'un bon ou un bloc de facture est rattaché ou
  crée un chantier à partir d'un nom lu non vide et que le fournisseur est
  connu, l'alias `(fournisseur_id, libellé lu)` est enregistré vers ce
  chantier (`valide_par` nul = automatique, `valide_le` = maintenant). Si
  cet alias existait « en attente » (`chantier_id` nul, ancien flux), il
  est rattaché et `chantier_id` est propagé aux autres bons et blocs qui
  l'attendaient (même propagation que `valider_alias`). Une alerte
  n'apprend rien.
- **Création** : `Chantier(nom_canonique=<libellé brut sans le code final
  entre parenthèses, espaces de bord retirés>, agence=None, client=None,
  actif=True, a_completer=True)`. Journal `chantier_cree_auto`
  (`utilisateur_id` nul, `apres` = nom, source « nom lu »/« légende »,
  document).
- **Journal** du rattachement : l'entrée `extraction_bl` existante porte
  `chantier_id`, `methode_chantier` (« nom connu », « ressemblance »,
  « légende », « création », « alerte ») et le score.

### 2.4 Alerte « Chantier à confirmer » (règle R18)

`rules/rules/R18.py`, pure : reçoit `ChantierIncertainControle(document_id,
nom_lu, legende, candidats: tuple[str, ...])` et renvoie une `Anomalie`
R18, gravité **moyenne**, `detail = {nom_lu, legende, candidats}` (noms
séparés par « / », « — » si absent), portée `document_id`. Test positif et
négatif. Catégorie `rattacher` dans `CATEGORIES_REGLE`. Libellé à l'écran :
« Chantier à confirmer ».

- Persistée par `synchroniser_anomalies(portee_document_id=<bon>,
  portee_regles=["R18"])` à chaque résolution du chantier d'un bon :
  une alerte qui n'a plus lieu d'être (correction du nom lu) est levée
  automatiquement.
- Le bon reste **sans chantier** tant que l'alerte est ouverte.
- **Action** : dans « À régler », l'alerte propose un bouton par candidat
  (« C'est <nom> ») et « Autre chantier… » (liste des chantiers, avec
  création possible). Choisir → `document.chantier_id` posé, alerte passée
  à `traitee` avec le commentaire automatique « Chantier choisi : <nom> »,
  journal `chantier_choisi`, photo rangée. Aucun alias appris.

**Factures** : un bloc n'a pas de légende ; un nom lu ambigu garde le flux
actuel (alias en attente, « Noms à rattacher » dans « À régler », R14).
Aucune alerte R18 sur un bloc.

### 2.5 Où la logique s'applique

- Extraction d'un BL (`ingest.extraction_bl`), y compris quand le
  fournisseur n'est pas reconnu (pas d'apprentissage d'alias dans ce cas).
- Correction du nom lu ou du fournisseur par l'admin
  (`ingest.corrections._resoudre_chantier_document`).
- Dépôt d'une facture (`ingest.factures`, bloc par bloc, sans légende).
- Reprise des données existantes (§2.8).

### 2.6 Signalement sur le site

- « À régler » : nouvelle section « Nouveaux chantiers à compléter »
  (chantiers `a_completer`, nombre de bons, lien vers la fiche). Ils
  comptent dans le nombre de problèmes à régler (pastille, accueil).
- Liste des chantiers et fiche : étiquette « À compléter ».
- Enregistrer la fiche du chantier (`PUT /api/chantiers/{id}`) ou le
  fusionner le fait sortir de « À compléter ».

### 2.7 Fusion

`POST /api/chantiers/{id}/fusionner` `{cible_id}` (admin) : le chantier
`id` (source) est fusionné dans `cible_id`.

- Déplacés vers la cible : `document.chantier_id`, `bloc_facture
  .chantier_id`, `chantier_alias.chantier_id`, `anomalie.chantier_id`. Une
  anomalie ouverte de la source dont l'identité existe déjà sur la cible
  (R16 « chantier silencieux ») est levée plutôt que déplacée.
- Source : `actif=False`, `a_completer=False`, `fusionne_dans_id=cible`.
  Jamais supprimée physiquement.
- Refus (409) : source = cible, source déjà fusionnée, cible fusionnée.
- Journal `chantier_fusionne` (`avant`/`apres` : source, cible, nombres
  déplacés). Photos des bons déplacés renommées.
- Les listes (chantiers, sélecteurs, bilan, tableau de bord) excluent les
  chantiers fusionnés ; la fiche d'un chantier fusionné affiche « Ce
  chantier a été fusionné dans <cible> » avec le lien.
- Bouton « Fusionner avec… » sur la fiche chantier (choix de la cible,
  confirmation qui dit ce qui va être déplacé).

### 2.8 Reprise

Commande `python -m app.cli rattacher-chantiers` (idempotente), lancée au
déploiement : chaque alias en attente passe par `reconnaitre_chantier` +
création/apprentissage (sans légende) ; puis chaque bon non archivé avec un
`chantier_brut` et sans chantier repasse par la logique complète. Affiche
le nombre de rattachés, créés et en alerte.

## 3. Gestion des comptes

Écran « Comptes » (admin seulement), accessible depuis Réglages.

- Liste : nom, e-mail, rôle, agence, identifiant Telegram, accès actif.
- **Créer** : nom, e-mail (identifiant de connexion, unique), rôle
  (admin/agent), agence, identifiant Telegram (facultatif, unique parmi
  les comptes), mot de passe provisoire (règles de longueur existantes de
  `creer_utilisateur`).
- **Modifier** : nom, e-mail, rôle, agence, identifiant Telegram.
- **Changer le mot de passe** : l'admin tape le nouveau (pas d'envoi
  d'e-mail). Coupe les sessions ouvertes du compte.
- **Retirer l'accès** (« Supprimer » côté client) : `is_active=False`,
  sessions coupées, photos Telegram ignorées ; le nom reste sur les bons.
  **Rétablir l'accès** possible.
- Garde-fous : on ne peut ni retirer son propre accès, ni retirer l'accès
  ou le rôle admin du dernier admin actif.
- Tout est journalisé (`compte_cree`, `compte_modifie`,
  `mot_de_passe_change`, `acces_retire`, `acces_retabli`), **jamais** le
  mot de passe ni son empreinte dans `avant`/`apres`.

## 4. Corrections

1. **Noms au lieu des identifiants dans le Journal** : toute valeur
   d'`avant`/`apres` qui désigne une personne (`confirme_par`,
   `utilisateur_id`…), un chantier, un fournisseur ou un compte s'affiche
   avec le nom, résolu **côté serveur** (le front n'a pas les
   référentiels). Identifiant inconnu → « (supprimé) ».
2. **Fiche fournisseur** : sélecteur de mois sur la fiche (même composant
   que la fiche chantier), reporté dans l'URL.
3. **Bons conformes** : les montants « Conforme » (accueil, fiche
   chantier, fiche fournisseur) deviennent cliquables et mènent à la liste
   des bons conformes du même périmètre (mois, chantier, fournisseur) ;
   chaque ligne ouvre la page du bon. « Conforme » a exactement la
   définition déjà utilisée par ces montants (aucune nouvelle définition).

## 5. Photos rangées

- Chaque photo de bon (`bl`, `enlevement`) a un **lien physique** (aucune
  copie, aucun espace disque en plus) dans
  `<DOCS_DIR>/bl/<AAAA>/<MM>/<JJ>_<déposant>_<chantier>_n<numéro
  interne>.<ext>`, date = jour du dépôt à l'heure de Paris. Segments
  assainis (minuscules, sans accents, `-` à la place des espaces et
  caractères spéciaux) ; « sans-chantier » si aucun chantier.
- Posé après la lecture du bon, et **renommé** à chaque changement de
  chantier (décision sur une alerte, correction, fusion, reprise).
- Un échec de rangement ne fait jamais échouer un dépôt : il est écrit
  dans les journaux techniques et rattrapé par la commande
  `python -m app.cli ranger-photos` (reconstruit tout, idempotente).
- Dossiers en 0750, liens sur le même fichier (0640 inchangé).

## 6. Données

Migration `0011` :

- `document.legende` TEXT NULL ;
- `chantier.a_completer` BOOLEAN NOT NULL DEFAULT false ;
- `chantier.fusionne_dans_id` UUID NULL, FK `chantier.id`.

## 7. Hors périmètre

Lot Prix, commentaires, IA, groupe Telegram de test (Ilane), création des
comptes en ligne de commande d'ici là (Ilane), sauvegardes restic (après le
1er octobre).

## 8. Points de vigilance pour les tests

1. Ressemblance : casse, accents, ordre des mots, code entre parenthèses,
   seuil exact (90 → reconnu, 89 → inconnu), égalité entre deux chantiers.
2. Chaque ligne de la table de décision a son test.
3. R18 : test positif et négatif ; levée automatique après correction ;
   choix d'un candidat qui ferme l'alerte.
4. Fusion : tout est déplacé, conflit R16, trois refus, chantier fusionné
   absent des listes, ses noms mènent à la cible.
5. Comptes : garde-fous (soi-même, dernier admin), sessions coupées, pas
   de mot de passe dans le journal, identifiant Telegram en double refusé.
6. Rangement : renommage, bon sans chantier, nom avec accents et `/`,
   échec qui ne bloque pas le dépôt.
7. Un bon déposé par Telegram avec légende arrive rangé dans le bon
   chantier de bout en bout (test d'intégration du dépôt).
