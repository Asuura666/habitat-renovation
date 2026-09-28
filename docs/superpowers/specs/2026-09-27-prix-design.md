# Lot Prix — grilles, contrôle des prix au bon, page « Prix à vérifier » — conception (27/09/2026)

Phase 3 de `docs/roadmap-octobre-2026.md` (§6), points 3, 4 et 5 de la demande
du client (§1.1). Session B, branche `feature/phase-3-prix`.
**À valider par Ilane avant toute implémentation.** Toutes les données citées
ici sont **inventées** : aucune valeur des grilles réelles du client ne figure
dans ce document.

---

## 1. Demande et décisions

### 1.1 Rappel de la demande (verbatim, §1.1 de la roadmap)

- **3. Grilles de prix** : chaque fournisseur a sa grille ; mise à jour
  manuelle ; import d'un fichier Excel avec un modèle fourni ; mise à jour
  automatique à partir des derniers prix après validation manuelle.
- **4. Contrôle des prix à la réception du BL** : historique des factures,
  grille du fournisseur en tenant compte de sa date, seuil en % réglable ; la
  règle de seuil déclenche l'alerte. (Internet et commentaire de l'IA : phase
  4, hors de ce lot.)
- **5. Page de suivi** : chaque jour, la liste des produits en alerte ; pour
  chacun, prix du bon, prix de la grille (et plus tard prix trouvé sur
  internet) ; un prix validé met la grille à jour.

### 1.2 Décisions d'Ilane (27/09/2026, cadrage de cette spec)

| # | Question | Décision |
| --- | --- | --- |
| D1 | À qui appartient une grille ? | **Une grille = un fournisseur.** Les deux grilles fournies sont celle de **Cedeo** (plomberie, avec références) et celle de **Point.P** (plâtre, isolation, sans référence, avec unité). |
| D2 | Modèle Excel | Une feuille, une ligne par produit : Référence (facultative), Désignation (obligatoire), Unité (facultative), Prix unitaire HT (obligatoire, nombre ou texte), Remise % (facultative), Marque et Famille (facultatives). Fournisseur et date d'effet choisis à l'écran. Aperçu avant confirmation. La grille Cedeo s'importe telle quelle (tous les onglets, « Article » = Désignation) ; la grille Point.P doit être recopiée une fois dans le modèle. |
| D3 | Prix lu sur un bon | Considéré comme **net** et comparé au **prix net** de la grille (prix − remise). Conversion d'unité quand le ratio de l'article est connu ; sinon **pas de comparaison** et « unités différentes » affiché. « M »/« ml », « SA »/« SAC » reconnus identiques. |
| D4 | Alertes | **Sept alertes distinctes** (R19 à R25, §5), chacune activable dans Réglages, plus un **interrupteur général éteint par défaut** qui cache tout avant la mise en production. Seuils par défaut : hausse 0 %, baisse 5 %, âge de grille 12 mois. |
| D5 | « Valider ce prix » | Nouvelle ligne de grille au prix du bon, **date d'effet = date du bon**, auteur et date gardés ; un produit absent est ajouté ; une ligne par produit sur la page Prix avec le nombre de bons ; la validation règle les alertes au **même prix**, les autres bons sont recontrôlés ; la référence est le prix de grille le plus récent en date d'effet. |
| D6 | « Contester » / « Ignorer » | Contester : alerte fermée, **commentaire obligatoire**, grille inchangée, pas de suivi de réclamation. Ignorer : alerte fermée, commentaire facultatif. Journalisés, jamais rouverts ; un **nouveau bon** au même prix redéclenche une alerte. |

Décisions de la roadmap reprises telles quelles : historique des prix
**jamais écrasé ni supprimé** (déclencheur PostgreSQL, vérifié par un test),
non affiché mais interrogeable ; page Prix **simple** ; l'humain décide ;
aucune IA dans ce lot ; contrôle **au bon** seulement (à la facture : phase 4).

### 1.3 Ce que montrent les deux grilles réelles (formes, pas valeurs)

- **Cedeo** : 7 onglets (un par famille), en-tête identique « Marque ·
  Référence · Article · Prix unitaire HT (€) · (sans titre) », environ 130
  produits, références numériques toutes différentes, **aucune unité, remise
  ni date** ; ≈ 40 % des prix stockés en texte (« 6.30 ») ; la 5ᵉ colonne,
  sans titre, répète la famille.
- **Point.P** : une feuille mise en page en deux blocs côte à côte avec des
  titres de famille fusionnés, **aucune référence**, désignations courtes
  (« Rail 48 » est la forme, pas une donnée), une unité par ligne (m², ml,
  sac, boîte, rouleau, unité). Le fichier contient aussi le contrôle manuel
  d'août : méthode « OK / À contrôler / ALERTE / NON IDENTIFIÉ » que les
  alertes R19, R20 et R22 reproduisent.
- Conséquence : chez Point.P, un produit ne se retrouve **que par son nom**,
  ce qui impose un calcul de correspondance adapté (§4.3).

---

## 2. Vue d'ensemble

```
Excel / saisie / validation ──► grille_prix (historique inaltérable)
                                       │  prix en vigueur à la date du bon
Bon déposé ─► lecture ─► lignes ──► contrôle des prix du bon (ingest/prix_bl.py)
                                       │  normalize/prix.py : produit, unités, prix net
                                       │  rules R19…R25    : alertes chiffrées
                                       ▼
                              anomalie (catégorie « prix »)
                                       │
                     « À régler » (compte)   « Prix à vérifier » (/prix)
                                                   │ Valider → nouvelle ligne de grille
```

Découpage en modules, conforme aux frontières de `CLAUDE.md` :

| Module | Contenu | Pur ? |
| --- | --- | --- |
| `extract/grille_excel.py` | lecture d'un fichier Excel de grille → `GrilleLue` (lignes, erreurs) | oui (openpyxl, octets en entrée, dataclasses en sortie) |
| `normalize/prix.py` | clé produit, correspondance de nom, prix net, comparaison d'unités | oui |
| `normalize/unites.py` | 3 variantes d'unités ajoutées (§4.4) | oui |
| `rules/rules/R19.py` … `R25.py`, `rules/engine.py` (`evaluer_prix_bl`, `REGLES_PRIX_BL`) | alertes | oui |
| `ingest/grilles.py` | grilles : lecture, saisie, retrait, import (aperçu, confirmation), modèle Excel | orchestrateur |
| `ingest/prix_bl.py` | contrôle des prix d'un bon, recontrôles, page Prix et ses actions | orchestrateur |
| `api/grilles.py`, `api/prix.py` | routes `/api/grilles/…`, `/api/prix/…` | entrée |
| `web/src/pages/GrilleFournisseur.tsx`, `web/src/pages/Prix.tsx` | écrans `/fournisseurs/:id/prix`, `/prix` | front |

---

## 3. Données — migration `0013_grilles_prix`

(`0012` est prise par les commentaires.)

### 3.1 Table `grille_import`

Une ligne par import confirmé d'un fichier (jamais pour un aperçu).

| Colonne | Type | Rôle |
| --- | --- | --- |
| `id` | UUID, clé | |
| `fournisseur_id` | UUID, FK `fournisseur`, non nul | |
| `nom_fichier` | texte, non nul | nom d'origine, 200 caractères au plus |
| `empreinte` | texte, non nul | SHA-256 du fichier |
| `chemin` | texte, non nul | copie gardée sous `DOCS_DIR/grilles/<fournisseur_id>/<id>.xlsx` (0640), incluse dans les sauvegardes des documents |
| `date_effet` | date, non nul | |
| `nb_nouveaux`, `nb_modifies`, `nb_inchanges`, `nb_erreurs` | entier, non nul | résumé figé |
| `auteur_id` | UUID, FK `utilisateur`, nullable | |
| `created_at` | horodatage | |

### 3.2 Table `grille_prix` — l'historique

Chaque changement de prix d'un produit **ajoute** une ligne. Rien n'est jamais
modifié ni supprimé.

| Colonne | Type | Rôle |
| --- | --- | --- |
| `id` | UUID, clé | |
| `fournisseur_id` | UUID, FK `fournisseur`, non nul | |
| `cle_produit` | texte, non nul | identité du produit dans la grille (§4.1) |
| `reference` | texte, nullable | telle que lue ou saisie |
| `designation` | texte, non nul | |
| `unite_brut` | texte, nullable | telle que lue (« ml », « SAC ») |
| `unite` | texte, nullable | code normalisé (`m`, `sac`…) ou nul si inconnue |
| `prix_ht` | numérique, non nul, `> 0` | prix catalogue HT |
| `remise_pct` | numérique, nullable, `0 ≤ x < 100` | |
| `prix_net` | numérique, non nul, `> 0` | `prix_ht × (1 − remise/100)`, arrondi à 4 décimales (`ROUND_HALF_UP`), calculé une fois à l'insertion |
| `marque`, `famille` | texte, nullable | affichage seulement |
| `date_effet` | date, non nul | à partir de quand ce prix vaut |
| `retire` | booléen, non nul, défaut faux | vrai = le produit sort de la grille à `date_effet` |
| `source` | texte, non nul, `CHECK IN ('import','saisie','validation')` | |
| `import_id` | UUID, FK `grille_import`, nullable | pour `source = 'import'` |
| `document_id` | UUID, FK `document`, nullable | bon d'origine, pour `source = 'validation'` |
| `ligne_libelle` | texte, nullable | copie du libellé de la ligne du bon validée (la ligne peut disparaître) |
| `auteur_id` | UUID, FK `utilisateur`, nullable | |
| `created_at` | horodatage, défaut `now()` | |

Contraintes et index :
- `CHECK (source <> 'import' OR import_id IS NOT NULL)` ;
  `CHECK (source <> 'validation' OR document_id IS NOT NULL)` ;
- index `(fournisseur_id, cle_produit, date_effet DESC, created_at DESC)`
  (prix en vigueur) ;
- **aucune** clé étrangère vers `anomalie` ni vers `ligne` : une suppression
  en cascade ferait un `UPDATE` que le déclencheur refuserait ;
- **déclencheurs** : `grille_prix_inalterable` `BEFORE UPDATE OR DELETE ...
  FOR EACH ROW` et `grille_prix_sans_truncate` `BEFORE TRUNCATE ... FOR EACH
  STATEMENT`, exécutant une fonction `grille_prix_refuser_modification()` qui
  lève `RAISE EXCEPTION 'historique des prix inaltérable'`. Le `downgrade()`
  supprime déclencheurs, fonction, puis tables (seul chemin de suppression :
  une migration descendante, jamais le code).

**Prix en vigueur** d'un produit à une date `d` : la ligne de
`(fournisseur_id, cle_produit)` de plus grande `date_effet ≤ d`, à égalité la
plus récente en `created_at` ; si elle est `retire`, le produit n'a pas de
prix à cette date. Si aucune ligne n'a de `date_effet ≤ d` mais qu'il en
existe une plus tard (grille importée après la date du bon), on prend **la
première** ligne postérieure et le détail de l'alerte le dit
(`grille_posterieure_au_bon: "oui"`). **Grille en vigueur aujourd'hui** :
même règle avec `d` = aujourd'hui (heure de Paris).

### 3.3 Modification d'une contrainte existante : `anomalie.ligne_id`

Les lignes d'un bon sont supprimées puis recréées à chaque relance de la
lecture, et une correction peut en retirer. Une alerte de prix posée sur une
ligne (comme R06 aujourd'hui, désactivée) bloquerait cette suppression
(clé étrangère sans `ON DELETE`). La migration passe
`fk_anomalie_ligne_id_ligne` en **`ON DELETE CASCADE`** :
- une alerte **ouverte** disparaît avec sa ligne et le contrôle la recrée
  sur la nouvelle ligne juste après (même principe que le rejeu actuel) ;
- une alerte **réglée** d'une ligne supprimée disparaît aussi : sa trace
  reste au journal (`anomalie_traitee`, `prix_valide`…), et la ligne de
  grille issue d'une validation garde `document_id` et `ligne_libelle`.
- `SET NULL` est écarté : deux alertes de la même règle sur le même bon
  deviendraient identiques pour l'index unique (`NULLS NOT DISTINCT`) et la
  suppression échouerait.

Noté dans `docs/dette.md` (une alerte réglée ne survit pas à la suppression
de sa ligne).

### 3.4 Réglages (`parametre`, clés `prix_…`)

`DefinitionParametre` reçoit deux champs, ajoutés **à la fin** avec une valeur
par défaut (aucune définition existante ne change) :
`interrupteur: bool = False` (valeur 0 ou 1, affichée « Oui / Non ») et
`groupe: str = ""` (titre de section dans Réglages ; vide = section
générale actuelle). Définitions ajoutées à la fin de `DEFINITIONS_PARAMETRES`,
groupe « Contrôle des prix des bons » :

| Clé | Libellé à l'écran | Défaut | Bornes |
| --- | --- | --- | --- |
| `prix_controle_bl_actif` | Contrôler les prix des bons | 0 (non) | interrupteur |
| `prix_alerte_plus_cher_grille` | Alerter : plus cher que la grille | 1 | interrupteur |
| `prix_alerte_plus_cher_dernier_prix` | Alerter : plus cher que la dernière fois | 1 | interrupteur |
| `prix_alerte_moins_cher_grille` | Alerter : moins cher que la grille | 1 | interrupteur |
| `prix_alerte_absent_grille` | Alerter : produit absent de la grille | 1 | interrupteur |
| `prix_alerte_reconnu_par_nom` | Alerter : produit reconnu seulement par son nom | 1 | interrupteur |
| `prix_alerte_unites_differentes` | Alerter : unités différentes | 1 | interrupteur |
| `prix_alerte_grille_ancienne` | Alerter : grille ancienne | 1 | interrupteur |
| `prix_seuil_hausse_pct` | Hausse tolérée avant alerte | 0 % | 0 – 100 |
| `prix_seuil_baisse_pct` | Baisse tolérée avant alerte | 5 % | 0 – 100 |
| `prix_age_grille_mois` | Âge à partir duquel une grille est ancienne | 12 mois | 1 – 60, entier |
| `prix_seuil_ressemblance_produit_pct` | Ressemblance minimale pour reconnaître un produit par son nom | 80 % | 50 – 100, entier |

Ces réglages restent **toujours visibles** (il faut pouvoir tout préparer
avant d'allumer l'interrupteur général). Modification journalisée comme les
autres (`parametre_modifie`).

---

## 4. Calculs purs (`normalize/prix.py`, `normalize/unites.py`)

### 4.1 Clé produit

- `normaliser_reference(ref)` : `normaliser_libelle` puis suppression des
  espaces ; une référence lue comme nombre par Excel (`4000493.0`) est
  ramenée à l'entier (`"4000493"`) avant, dans `extract`.
- `cle_produit(reference, designation)` : `"ref:" + normaliser_reference(r)`
  si la référence est non vide, sinon `"nom:" + normaliser_libelle(d)`.
- Conséquence : dans une même grille, deux lignes de même référence (ou, sans
  référence, de même désignation normalisée) sont **le même produit**.

### 4.2 Prix net

`prix_net(prix_ht, remise_pct) -> Decimal` : `prix_ht` si pas de remise,
sinon `prix_ht × (100 − remise_pct) / 100`, arrondi à 4 décimales
(`ROUND_HALF_UP`). Refuse `prix_ht ≤ 0` et une remise hors `[0, 100[`
(`ValueError`).

### 4.3 Correspondance d'un nom de produit

La fonction existante `ressemblance` (nom entier contre nom entier, pensée
pour les chantiers) ne distingue pas un nom de grille court de ses voisins face
au nom long imprimé sur le bon. Mesure faite sur les vraies paires Point.P :
les bonnes paires et les mauvaises tombent toutes entre 41 et 58.

Nouvelle fonction `ressemblance_produit(a, b) -> int` (0-100, entière) :
1. **mots** d'un nom : `normaliser_libelle`, puis séparation lettres/chiffres
   (`70mm` → `70 mm`, `d14mm` → `d 14 mm`), découpage aux espaces, ensemble
   des mots ;
2. **couverture** de `x` dans `y` : `⌊100 × |mots(x) ∩ mots(y)| / |mots(x)|⌋`
   (0 si `x` n'a aucun mot) ;
3. `ressemblance_produit(a, b) = max(couverture(a dans b), couverture(b dans a))`.

Exemples inventés (même forme que les vraies paires) :

| Bon | Grille | Score |
| --- | --- | --- |
| `CLOISON STD KX 48 NF 3M` | `Cloison 48` | 100 |
| `CLOISON STD KX 70 NF 3M` | `Cloison 48` | 50 |
| `ENDUIT PRO E2 LENT 25KG` | `E2 lent` | 100 |
| `ENDUIT PRO E2 LENT 25KG` | `E3 lent` | 66 |
| `ISOLANT LAINE ALPHA 70MM` | `Alpha 70` | 100 |
| `ISOLANT LAINE ALPHA 70MM` | `Alpha 45` | 50 |

`trouver_produit(ligne, produits, seuil) -> Correspondance | None` :
1. si la ligne a un code et qu'un produit a la même référence normalisée →
   `Correspondance(produit, methode="reference", ressemblance=100)` ;
2. sinon, score de chaque produit **sur sa désignation** ; on garde le
   meilleur s'il atteint `seuil` et qu'il est **seul** à ce score, à égalité
   départagée par `ressemblance` (l'ancienne) puis rien : si l'égalité
   persiste, **aucune correspondance** et la liste des candidats est rendue
   (`candidats`, 3 au plus) pour l'alerte « absent de la grille » ;
3. résultat `methode="nom"` avec le score.

La même fonction sert à retrouver le produit dans les lignes de factures
passées (§6.3).

### 4.4 Unités

- `normalize/unites.py` : variantes **ajoutées** (rien de retiré) : `SA` →
  `sac`, `BT` → `boite`, `PI` → `u`. (`M`/`ML` sont déjà `m`, `RL` déjà
  `rouleau`.)
- `unites_comparables(unite_bon, unite_ref, article) -> Conversion` :
  - mêmes codes normalisés, ou toutes deux inconnues/absentes → facteur 1 ;
  - l'une est le conditionnement de l'article (`unite_cdt`) et l'autre son
    unité de facturation (`unite_fact`), avec un ratio **validé** et > 0 →
    facteur `ratio` ou `1/ratio` : le prix de référence est ramené à l'unité
    du bon (ex. grille au kg, bon au seau de 15 kg → prix grille × 15) ;
  - sinon → `Conversion(possible=False)`.
- Une unité connue d'un seul côté (bon « sac », grille sans unité) est traitée
  comme comparable (facteur 1) : c'est le cas de toute la grille Cedeo, qui
  n'a pas d'unité. Le détail de l'alerte affiche les deux unités telles
  quelles, l'humain juge.

---

## 5. Les alertes (règles pures R19 à R25)

### 5.1 Entrées (`rules/modeles.py`, ajouts à la fin)

```python
@dataclass(frozen=True)
class ReferencePrix:
    prix: Decimal  # prix net, déjà ramené à l'unité du bon
    unite: str | None  # unité de la référence, telle qu'affichée
    date: date
    comparable: bool  # False : unités non convertibles
    methode: str  # "reference" ou "nom"
    ressemblance: int  # 100 si par référence
    designation: str
    source: str  # "grille" ou "facture"
    numero_facture: str | None = None
    grille_posterieure_au_bon: bool = False


@dataclass(frozen=True)
class LignePrixBl:
    document_id: uuid.UUID
    ligne_id: uuid.UUID
    designation: str
    code: str | None
    prix_bon: Decimal  # pu_ht lu sur le bon, > 0
    unite_bon: str | None
    date_bon: date
    grille: ReferencePrix | None  # None : produit absent de la grille
    candidats: tuple[str, ...]  # si absent faute de départage
    dernier_prix: ReferencePrix | None  # dernière facture, None si aucune


@dataclass(frozen=True)
class ParametresPrixBl:
    seuil_hausse_pct: Decimal = Decimal("0")
    seuil_baisse_pct: Decimal = Decimal("5")
    age_grille_mois: int = 12
    aujourdhui: date | None = None  # pour R25, fourni par ingest
```

### 5.2 Les sept règles

Écart en % : `(prix_bon − ref) / ref × 100`, arrondi à 0,1
(`ROUND_HALF_UP`), calculé seulement si la référence est comparable. Seuils
comparés **strictement** : avec 0 %, tout centime de plus déclenche.
Toutes posent `document_id` et `ligne_id`, jamais `article_id` (la règle des
90 jours d'ignorance ne doit pas s'appliquer : décision D6, un nouveau bon
redéclenche). `detail` : chaînes, montants à 2 ou 4 décimales comme le
reste du moteur, dates ISO.

| Règle | Titre à l'écran | Condition | Gravité | Détail (clés) |
| --- | --- | --- | --- | --- |
| R19 | Plus cher que la grille | grille comparable et `prix_bon > grille × (1 + seuil_hausse/100)` | haute | `produit, code, prix_bon, unite_bon, date_bon, prix_grille, unite_grille, date_grille, ecart_pct, methode, ressemblance, designation_grille` (+ `grille_posterieure_au_bon`) |
| R20 | Plus cher que la dernière fois | dernier prix comparable et `prix_bon > dernier × (1 + seuil_hausse/100)` | haute | `produit, code, prix_bon, unite_bon, date_bon, dernier_prix, unite_dernier_prix, date_dernier_prix, numero_facture, ecart_pct, methode, ressemblance` |
| R21 | Moins cher que la grille | grille comparable et `prix_bon < grille × (1 − seuil_baisse/100)` | basse | comme R19 |
| R22 | Produit absent de la grille | `grille is None` | basse | `produit, code, prix_bon, unite_bon, date_bon, candidats` (« — » si aucun) |
| R23 | Produit reconnu seulement par son nom | grille trouvée avec `methode == "nom"` | basse | `produit, code, designation_grille, ressemblance, prix_bon, prix_grille` |
| R24 | Unités différentes | grille **ou** dernier prix présent avec `comparable == False` | moyenne | `produit, code, unite_bon, unite_grille, unite_dernier_prix, prix_bon` (« — » pour l'absent) |
| R25 | Grille ancienne | grille présente et `date_grille` antérieure de plus de `age_grille_mois` mois à `aujourdhui` | basse | `produit, code, date_grille, age_mois, prix_grille` |

Combinaisons : R19/R21 et R20 sont indépendantes (on peut avoir les deux) ;
R19 et R21 s'excluent ; R22 exclut R19, R21, R23, R25 ; une référence non
comparable n'alimente que R24. Une ligne sans `pu_ht`, à prix nul ou négatif,
ou de type autre qu'`article` n'est pas contrôlée (aucune alerte, jamais
« conforme »).

### 5.3 Moteur

`rules/engine.py` : `REGLES_PRIX_BL = frozenset({"R19", …, "R25"})` et
`evaluer_prix_bl(lignes: Sequence[LignePrixBl], parametres:
ParametresPrixBl, regles_actives: frozenset[str] | None = None) ->
tuple[Anomalie, ...]`. Comme pour R07-R09, une règle absente de
`regles_actives` **n'est pas appelée** (pas seulement filtrée). Invariants de
`test_engine.py` : les quatre ensembles `REGLES_FACTURE`, `REGLES_SUIVI`,
`REGLES_CHANTIER`, `REGLES_PRIX_BL` sont deux à deux disjoints ;
`tests/test_regle_anomalie_couverture.py` : `RegleAnomalie` = leur union.

Chaque règle a au moins : un test positif, un test négatif, un test à la
limite exacte du seuil (égalité → pas d'alerte) et, pour R19/R20/R21, un test
avec conversion d'unité.

---

## 6. Contrôle des prix d'un bon (`ingest/prix_bl.py`)

### 6.1 `controler_prix_bl(session, document_id) -> int`

Retourne le nombre d'alertes de prix ouvertes du bon après contrôle.
1. Lit les réglages `prix_…`. Si `prix_controle_bl_actif` vaut 0 : ne fait
   rien, ne supprime rien (les alertes existantes restent, cachées par §6.5).
2. Document `bl` ou `enlevement`, non archivé, avec `fournisseur_id` ; sinon
   rien. Date du bon = `date_doc`, sinon date de dépôt (heure de Paris).
3. Pour chaque ligne `article` à `pu_ht > 0` : produit de la grille en vigueur
   à la date du bon (§3.2, §4.3), dernier prix facturé (§6.3), unités (§4.4)
   → `LignePrixBl`.
4. `evaluer_prix_bl(..., regles_actives=` règles dont l'interrupteur vaut 1`)`.
5. `synchroniser_anomalies(session, anomalies=..., portee_document_id=
   document_id, portee_regles=` règles actives`)` : les alertes ouvertes qui
   ne se vérifient plus sont levées (journal `anomalie_levee`), les autres
   mises à jour, les réglées jamais rouvertes. Les règles éteintes ne sont
   pas dans la portée : leurs alertes ouvertes restent, cachées.
6. Ne commite pas : l'appelant tient la transaction.

### 6.2 Quand le contrôle tourne

| Événement | Appel | Transaction |
| --- | --- | --- |
| Lecture d'un bon (premier passage ou relance) | `extraction_bl.enregistrer_extraction_bl`, **après** `_rapprocher_si_numero`, dans les deux chemins : `await _controler_prix_sans_echec(session, document_id)` | la sienne : `controler_prix_bl` puis `commit` ; toute exception est attrapée, `rollback`, journalisée par le logger (`logger.exception`, sans contenu du bon) ; l'extraction, déjà commitée, n'échoue jamais |
| Correction des lignes (`corrections.corriger_lignes`) | après le `commit` de la correction, même enveloppe | idem |
| Validation, saisie ou import d'un prix de grille | recontrôle (§6.4) | idem, après le commit de la grille |
| Bouton « Recontrôler les bons » de la page Prix, et commande `python -m app.cli controler-prix [--depuis AAAA-MM-JJ]` | recontrôle de tous les bons non archivés datés depuis le 1ᵉʳ du mois précédent (ou `--depuis`) | un commit par bon |

La modification dans `extraction_bl.py` (fichier partagé avec la session A)
se limite à une fonction ajoutée et deux lignes d'appel.

### 6.3 Dernier prix facturé

Lignes `article` des documents `facture` du même fournisseur, `date_doc ≤
date du bon`, `pu_ht > 0`. Produit retrouvé par code (égalité de
`normaliser_reference(code_brut)`), sinon par `ressemblance_produit` ≥ seuil
sur `article_brut`. Parmi les lignes retenues, la plus récente (`date_doc`
puis `created_at`) ; prix net = `pu_ht × (1 − remise_pct/100)` si remise ;
unité = `unite_fact` de l'article rattaché, sinon `unite_brut` ; conversion
comme §4.4. Pas de fenêtre de temps (l'historique est encore mince). Les
factures Point.P ne sont pas encore lues (parseur absent) : chez ce
fournisseur, R20 ne se déclenchera qu'une fois ce parseur fait. Les prix des
**bons précédents** ne comptent pas comme « dernier prix payé » (la demande
parle des factures) : noté comme évolution possible.

### 6.4 Recontrôles après un changement de grille

- **Import ou saisie** d'un prix du fournisseur F avec date d'effet `d` :
  bons de F non archivés datés à partir de `d`.
- **Validation** d'un prix : bons portant une alerte de prix ouverte sur le
  même produit (même `cle_produit` de grille, ou même désignation normalisée
  pour un produit absent).
- Chaque bon dans sa propre transaction ; un échec est journalisé par le
  logger et n'annule pas le changement de grille.

### 6.5 Masquage (interrupteurs)

- `ingest/commun.py` : importe `REGLES_PRIX_BL` de `rules.engine` (comme
  le reste d'`ingest`) et ajoute la fonction `async regles_masquees(session) -> frozenset[str]` = règles
  désactivées actuelles (`regles_desactivees()`, inchangée) ∪ toutes les
  règles `REGLES_PRIX_BL` si l'interrupteur général vaut 0, sinon celles dont
  l'interrupteur vaut 0.
- `ingest/anomalies.condition_regles_actives` reçoit un paramètre
  `exclues: frozenset[str] | None = None` (défaut : comportement actuel) ;
  chaque lecture qui l'utilise (`_requete_anomalies`,
  `compter_anomalies_ouvertes`, `compter_anomalies_hautes_ouvertes`,
  `bilan`, `comparaison_bl`, `a_traiter`) passe `await
  regles_masquees(session)`. `traiter_anomalie` refuse une alerte masquée
  (404), comme aujourd'hui.
- `CompteProblemes.controle_prix_actif` vaut vrai si le contrôle des
  factures **ou** celui des bons est allumé : le filtre « Prix » d'« À
  régler » apparaît alors sans changement du front.
- Catégorie `prix` pour R19 à R25 dans `CATEGORIES_REGLE`.
- Éteindre une alerte ne supprime rien : réallumer fait réapparaître ses
  alertes ouvertes (et le prochain contrôle les remet à jour).

---

## 7. Grilles (`ingest/grilles.py`, `extract/grille_excel.py`)

### 7.1 Lecture d'un fichier (`extract/grille_excel.py`, pur)

`lire_grille_excel(contenu: bytes) -> GrilleLue` avec `GrilleLue(lignes:
tuple[LigneGrilleLue, ...], erreurs: tuple[ErreurGrille, ...],
feuilles_ignorees: tuple[str, ...])`.

- Refus immédiat (`FichierGrilleInvalide`, message en français) : pas un
  `.xlsx` (signature ZIP `PK\x03\x04` et ouverture openpyxl), fichier
  protégé, plus de 20 000 lignes utiles au total.
- openpyxl en `read_only=True, data_only=True` (valeur calculée des
  formules). **defusedxml** installé (nouvelle dépendance) pour neutraliser
  les fichiers XML piégés ; `openpyxl` et `defusedxml` passent par
  `pip-audit`.
- **Chaque feuille** est lue. En-tête cherché dans les 10 premières lignes :
  ligne qui contient une colonne Désignation **et** une colonne Prix.
  Correspondance des titres, après `normaliser_libelle` :

  | Champ | Titres reconnus |
  | --- | --- |
  | Référence | `reference`, `ref`, `code`, `code article`, `ref fournisseur` |
  | Désignation | `designation`, `article`, `libelle`, `produit` |
  | Unité | `unite`, `u`, `unite de vente` |
  | Prix | tout titre commençant par `prix` ou `pu` (`prix unitaire ht`, `prix ht`, `pu ht`…) ; s'il y en a plusieurs, celui qui contient `ht` |
  | Remise | `remise`, `remise %`, `remise pct` |
  | Marque | `marque`, `fabricant` |
  | Famille | `famille`, `categorie` |

  Une feuille sans en-tête reconnu (ex. « Mode d'emploi ») va dans
  `feuilles_ignorees`. Une colonne sans titre est ignorée. Sans colonne
  Famille, la famille = **nom de la feuille** (cas Cedeo).
- Chaque ligne après l'en-tête : entièrement vide → ignorée ; sinon
  `LigneGrilleLue(feuille, numero_ligne, reference, designation, unite_brut,
  prix_ht, remise_pct, marque, famille)` ou une `ErreurGrille(feuille,
  numero_ligne, message)` :
  - désignation vide → « désignation manquante » ;
  - prix vide → « prix manquant » ; texte illisible → « prix illisible :
    « … » » ; ≤ 0 → « le prix doit être supérieur à 0 » ; texte accepté :
    espaces, `€`, virgule ou point décimal (`"6,30 €"`, `"6.30"`) ;
  - remise illisible ou hors `[0, 100[` → erreur ;
  - référence numérique `4000493.0` → `"4000493"` ; texte gardé tel quel
    (espaces de bord retirés).
- **Doublons dans le fichier** (même clé produit, §4.1) : la seconde
  occurrence est une erreur « même produit déjà présent ligne N (feuille) ».

### 7.2 Aperçu et confirmation (`ingest/grilles.py`)

`apercu_import(session, fournisseur_id, contenu, nom_fichier, date_effet) ->
ApercuImport` (ne modifie rien) : compare chaque ligne lue au **prix en
vigueur à `date_effet`** du même produit :
- `nouveaux` : produit absent → sera ajouté ;
- `modifies` : prix net ou unité différents → ancien et nouveau prix ;
- `inchanges` : nombre seulement (aucune ligne d'historique ne sera créée) ;
- `absents_du_fichier` : produits en vigueur qui ne figurent pas dans le
  fichier → **information seulement**, ils ne sont pas retirés ;
- `erreurs`, `feuilles_ignorees`.

`importer_grille(...)` : relit le fichier (même calcul), refuse s'il n'y a
aucune ligne valide, puis dans **une** transaction : `grille_import`, une
ligne `grille_prix` (`source="import"`) par nouveau ou modifié, copie du
fichier, journal `grille_importee` (`cible_table="grille_import"`, `apres` :
fournisseur, nom du fichier, date d'effet, compteurs). Les lignes en erreur
sont ignorées (le bouton de l'écran le dit). Un import au contenu identique
au précédent ne crée aucune ligne de prix. Ensuite recontrôle §6.4.

Limites : 5 Mo par fichier (lecture bornée à 5 Mo + 1 octet, 413 au-delà,
comme le dépôt de factures) ; date d'effet entre le 01/01/2000 et
aujourd'hui + 1 an.

### 7.3 Modèle Excel (`GET /api/grilles/modele`)

Généré à la volée avec openpyxl (jamais un fichier du client) : feuille
« Grille » avec l'en-tête du modèle en gras, colonne Prix au format nombre à
2 décimales, largeurs ajustées, **deux lignes d'exemple inventées** (une avec
référence et remise, une sans référence avec unité) ; feuille « Mode
d'emploi » : une phrase par colonne (obligatoire ou non, formats acceptés),
et rappel que le fournisseur et la date d'effet se choisissent à l'import.
Nom : `modele-grille-de-prix.xlsx`. La feuille « Mode d'emploi » est
ignorée à l'import (pas d'en-tête reconnu) ; les deux lignes d'exemple, si
on les laisse, sont importées comme les autres : le mode d'emploi dit de les
effacer.

### 7.4 Saisie et retrait à l'écran

- `enregistrer_prix(session, fournisseur_id, saisie, auteur_id)` : saisie =
  référence (facultative), désignation, unité, prix HT, remise, date d'effet
  (défaut aujourd'hui), marque, famille. Même produit (clé) → modification :
  nouvelle ligne `source="saisie"`. Journal `grille_prix_saisi` (`avant` :
  prix en vigueur ou rien ; `apres` : nouveau prix). Refuse (422) un prix
  identique au prix en vigueur à cette date (« ce prix est déjà celui de la
  grille »). Recontrôle §6.4.
- `retirer_produit(session, fournisseur_id, cle_produit, date_effet,
  auteur_id)` : nouvelle ligne `retire=True` reprenant le dernier prix (non
  nul, pour les contraintes). Journal `grille_prix_retire`.
- `historique_produit(session, fournisseur_id, cle_produit)` : toutes les
  lignes du produit, de la plus récente à la plus ancienne (API seulement,
  pas d'écran : « non affiché mais interrogeable »).

---

## 8. Page « Prix à vérifier » (`/prix`) et ses actions

### 8.1 Liste (`GET /api/prix/alertes?periode=jour|tout&fournisseur_id=`)

- Alertes **ouvertes** R19-R25 non masquées ; `periode=jour` (défaut
  « tout ») : créées aujourd'hui (heure de Paris).
- **Regroupées par produit** : fournisseur + clé produit de la grille si
  trouvée, sinon clé calculée sur la ligne du bon (§4.1).
- Une rangée par groupe, **peu d'informations** :
  - produit (désignation du bon, code en petit) et fournisseur ;
  - prix du bon (et son unité) — celui du **bon le plus récent** du groupe —,
    avec « sur 3 bons » et « 2 prix différents » si c'est le cas ;
  - prix de la grille (date) ou « absent de la grille » ;
  - dernier prix facturé (date) ou « — » ;
  - écart (le plus grand des deux écarts calculés, avec sa flèche) ;
  - ressemblance (« par référence » ou « 83 % ») ;
  - la ou les alertes, en mots (« Plus cher que la grille ») ;
  - lien vers le bon le plus récent.
- Tri : gravité haute d'abord, puis écart décroissant, puis date du bon.
- Le détail complet de chaque alerte reste accessible (un clic ouvre le
  problème dans « À régler », qui affiche la justification chiffrée).
- La réponse porte pour chaque groupe `anomalie_ids` et `ligne_id` du bon le
  plus récent : les actions les renvoient.

### 8.2 Actions

| Action | Route | Effet |
| --- | --- | --- |
| Valider ce prix | `POST /api/prix/valider` `{anomalie_ids, ligne_id}` | Revérifie que toutes les alertes sont ouvertes, de prix, du même groupe (sinon 409, rien n'est fait). Nouvelle ligne `grille_prix` `source="validation"` : prix = prix du bon de `ligne_id` (sans remise), unité du bon, date d'effet = date de ce bon, référence/désignation/marque/famille = celles du produit de la grille s'il existe, sinon code et désignation du bon ; `document_id`, `ligne_libelle`, auteur. Les alertes du groupe dont le prix du bon est **égal** → `traitee`, commentaire « Prix validé : 12,34 € (grille mise à jour) ». Journal `prix_valide` (produit, ancien prix de grille, nouveau prix, date d'effet, nombre d'alertes réglées). Commit, puis recontrôle §6.4 (les bons à un autre prix restent ou sortent selon la nouvelle grille). |
| Contester | `POST /api/prix/contester` `{anomalie_ids, commentaire}` | Commentaire obligatoire (1-500 caractères). Toutes les alertes → `traitee`, commentaire « Contesté : … ». Grille inchangée. Journal `prix_conteste`. |
| Ignorer | `POST /api/prix/ignorer` `{anomalie_ids, commentaire?}` | Toutes → `ignoree`, commentaire saisi ou « Ignoré depuis la page Prix ». Journal `prix_ignore`. |
| Recontrôler les bons | `POST /api/prix/recontrole` | §6.2 ; renvoie le nombre de bons contrôlés et d'alertes ouvertes. Journal `prix_recontrole`. |

Pour chaque alerte fermée, l'entrée habituelle `anomalie_traitee` ou
`anomalie_ignoree` est aussi écrite (le journal reste complet côté « À
régler »). Une alerte de prix réglée depuis « À régler » (sans passer par la
page Prix) ne touche pas la grille.

### 8.3 Écran

- Titre « Prix à vérifier », sous-titre du nombre de produits en alerte.
- Si l'interrupteur général est éteint : message « Le contrôle des prix des
  bons est éteint. Il s'allume dans Réglages. » et lien ; pas de liste.
- Filtres : « Aujourd'hui / Tout », fournisseur. Bouton « Recontrôler les
  bons ».
- Téléphone : une carte par produit ; ordinateur : tableau à 6 colonnes au
  plus. Trois boutons par rangée : **Valider ce prix** (principal),
  **Contester**, **Ignorer** ; Contester et Ignorer ouvrent une zone de
  commentaire sur place. Après action : la rangée disparaît, message bref
  (« Grille mise à jour »).
- Aucun code de règle, aucun mot technique (« OCR », « alias », « clé »).
- Lien « Prix » dans la navigation admin (`Gabarit.tsx`, une ligne), après
  « Fournisseurs ». Les agents n'y ont pas accès (routes `admin_requis`).
- « À régler » : les alertes R19-R25 y apparaissent comme les autres, avec
  phrase et titre (`ui/libelles.ts`) ; `ProblemeDetail` affiche un lien
  « Voir sur la page Prix » pour la catégorie prix.

Phrases (`phraseProbleme`, exemples) :
- R19 : « Plaque std 13 : 7,90 € sur le bon au lieu de 7,50 € dans la grille
  (du 01/01/2026), +5,3 %. »
- R20 : « … : 7,90 € sur le bon, 7,20 € sur la facture F123 du 12/08/2026,
  +9,7 %. »
- R21 : « … : 6,80 € sur le bon au lieu de 7,50 € dans la grille (…),
  −9,3 %. »
- R22 : « … : produit absent de la grille (7,90 € sur le bon). Produits
  proches : … »
- R23 : « … : reconnu dans la grille comme « Plaque std 13 » par son nom
  (ressemblance 83 %). »
- R24 : « … : unité du bon (sac) différente de celle de la grille (kg),
  comparaison impossible. »
- R25 : « … : prix de grille du 01/01/2025, vieux de 20 mois. »

---

## 9. Grille d'un fournisseur (`/fournisseurs/:id/prix`)

- Lien « Grille de prix » sur la fiche fournisseur (`FicheFournisseur.tsx`,
  une ligne près de l'en-tête).
- En-tête : nom du fournisseur, nombre de produits, date du dernier import.
- Recherche (référence ou désignation, côté serveur :
  `GET /api/grilles/fournisseurs/{id}?recherche=`), liste des **prix en
  vigueur aujourd'hui** : désignation, référence, unité, prix net (et prix +
  remise si remise), date d'effet, famille ; 50 par page.
- « Modifier » sur une rangée ouvre un petit formulaire (prix, remise, unité,
  date d'effet) ; « Ajouter un produit » : formulaire complet ; « Retirer de
  la grille » avec confirmation.
- Section « Importer un fichier » : « Télécharger le modèle », choix du
  fichier, date d'effet (défaut aujourd'hui), bouton « Voir l'aperçu » ;
  l'aperçu montre les compteurs, les 50 premiers nouveaux et modifiés (ancien
  → nouveau), les erreurs ligne par ligne, les produits absents du fichier
  (repliés) ; bouton « Importer 128 prix » (« … — 3 lignes en erreur seront
  ignorées ») ; puis résumé.
- Admin seulement.

---

## 10. API

| Méthode et route | Accès | Rôle |
| --- | --- | --- |
| `GET /api/grilles/modele` | admin | modèle Excel |
| `GET /api/grilles/fournisseurs/{id}` `?recherche=&page=` | admin | prix en vigueur |
| `GET /api/grilles/fournisseurs/{id}/produits/{cle}/historique` | admin | historique d'un produit |
| `POST /api/grilles/fournisseurs/{id}/prix` | admin | saisie (201) |
| `POST /api/grilles/fournisseurs/{id}/retrait` `{cle_produit, date_effet}` | admin | retrait |
| `POST /api/grilles/fournisseurs/{id}/import/apercu` (multipart `fichier`, `date_effet`) | admin | aperçu |
| `POST /api/grilles/fournisseurs/{id}/import` (idem) | admin | import (201) |
| `GET /api/prix/alertes` | admin | page Prix |
| `POST /api/prix/valider`, `/contester`, `/ignorer`, `/recontrole` | admin | actions |

Erreurs : 404 fournisseur, produit ou alerte inconnus ; 409 alertes déjà
réglées ou de groupes différents ; 413 fichier trop gros ; 422 fichier
illisible, saisie invalide, aucune ligne valide. Messages en français, et le
front les traduit en phrases (même principe que les commentaires). Les
`POST` passent par le contrôle d'origine existant.

---

## 11. Journal

Actions ajoutées (libellés dans `web/src/lib/journal.ts`) :
`grille_importee` « Grille importée », `grille_prix_saisi` « Prix de grille
saisi », `grille_prix_retire` « Produit retiré de la grille »,
`prix_valide` « Prix validé », `prix_conteste` « Prix contesté »,
`prix_ignore` « Alerte de prix ignorée », `prix_recontrole` « Prix des bons
recontrôlés ». Aucun identifiant technique affiché.

---

## 12. Tests

- **Purs** (sans base ni réseau) : `extract/tests/test_grille_excel.py`
  (fichiers **générés par le test** avec openpyxl : en-têtes variés, plusieurs
  feuilles, feuille sans en-tête, prix texte, virgule, `€`, référence
  numérique, doublon, prix nul, remise invalide, formule, fichier non
  `.xlsx`, trop de lignes) ; `normalize/tests/test_prix.py` (clé, prix net,
  `ressemblance_produit` avec le tableau §4.3, `trouver_produit` : référence,
  nom, égalité → aucun, seuil ; unités : identiques, conversion par ratio
  dans les deux sens, ratio non validé, une seule unité connue) ;
  `rules/tests/test_R19.py` … `test_R25.py` (positif, négatif, limite) ;
  `test_engine.py` (`evaluer_prix_bl`, règles non appelées si inactives,
  ensembles disjoints).
- **Base** : historique — `UPDATE`, `DELETE` et `TRUNCATE` sur `grille_prix`
  refusés (test explicite, exigence de la roadmap) ; prix en vigueur à une
  date (avant, entre, après deux lignes ; retrait ; grille postérieure au
  bon) ; import (aperçu sans écriture, confirmation, import identique sans
  nouvelle ligne, lignes en erreur ignorées, fichier gardé) ; saisie et
  retrait ; `controler_prix_bl` sur un bon inventé (chaque alerte, conversion,
  interrupteurs, alertes levées quand le prix de grille change, jamais
  rouvertes) ; **relance de la lecture** d'un bon en alerte (la cascade
  fonctionne, l'alerte est recréée) ; l'extraction n'échoue pas si le
  contrôle lève une exception ; masquage (interrupteur général, par alerte,
  comptes d'« À régler ») ; page Prix (regroupement, période, valider /
  contester / ignorer, 409) ; migration aller-retour et absence de dérive.
- **API** : accès admin seulement (agent 403, anonyme 401), 413, 422, 409,
  contrôle d'origine.
- **Documents réels** (sautés si absents, comme les tests existants) :
  `tests/test_grilles_reelles.py` lit la grille Cedeo rangée dans
  `tests/fixtures/grilles/` : zéro erreur, nombre de produits cohérent, aucune
  valeur affichée dans la sortie du test.
- **Front** : typecheck, build, vérification visuelle (375 px et 1 280 px)
  des deux pages avec des données inventées.

---

## 13. Hors périmètre et suites

- Contrôle des prix **à la facture** (remplace R07-R09), prix trouvé sur
  internet, commentaire de l'IA sur l'écart : phase 4.
- Suivi des réclamations fournisseur après « Contester ».
- Prix des bons précédents comme « dernier prix payé » (§6.3).
- Lecture de la remise imprimée sur un bon.
- Parseur des factures Point.P (déjà bloqué, hors phase 3) : sans lui, R20 ne
  se déclenche pas chez Point.P.
- Import d'une grille mise en page librement (blocs côte à côte) : il faut le
  modèle.
- Tâche planifiée quotidienne : inutile, le contrôle tourne à chaque dépôt et
  la page lit l'état courant ; « du jour » = filtre.

## 14. Points d'attention pour le déploiement (session A, avec l'accord d'Ilane)

- Migration `0013` (tables, déclencheurs, clé étrangère de `anomalie`).
- Nouvelles dépendances `openpyxl`, `defusedxml`.
- Les sauvegardes (phase 2) doivent tourner avant le premier import réel.
- En production, l'interrupteur général reste éteint ; ordre conseillé :
  importer les grilles, vérifier la page Grille, allumer, cliquer
  « Recontrôler les bons ».
