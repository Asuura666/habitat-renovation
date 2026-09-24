# Évolutions proposées

Propositions à faire à Ilane : chacune est **hors cahier des charges**
(`docs/cahier-des-charges.md` fait foi — rien ici n'est construit tant que ce
n'est pas demandé), rédigée pour être présentée telle quelle. L'effort est un
ordre de grandeur (temps de construction pour ce projet, un développeur,
tests compris), pas un devis. Aucune de ces propositions n'est urgente ni
bloquante pour l'usage actuel de l'application.

## a. Import des chantiers en masse depuis Excel

**Besoin.** Aujourd'hui, un chantier se crée un par un : soit via
« Nouveau chantier » sur l'écran Chantiers (`web/src/pages/ChantiersListe.tsx`),
soit à partir d'un « Chantier à rattacher » repéré sur l'écran « À régler »
(le premier document qui le cite crée ce chantier « à rattacher », validé
une fois identifié) — plus, au démarrage d'une agence, un import ponctuel
fait directement en base par l'intégrateur, jamais par un geste de
l'équipe. Réglages ne gère pas les chantiers. Si Habitat & Rénovation
reçoit d'un coup la liste de tous les chantiers d'une agence (nom, agence,
client) dans un fichier Excel, il n'y a aujourd'hui aucun moyen de les
charger sans les ressaisir un par un ou sans repasser par l'intégrateur.

**Proposition.** Un écran d'import sur l'écran Chantiers (à côté de
« Nouveau chantier ») : dépôt d'un fichier Excel (colonnes nom, agence,
client), aperçu des lignes reconnues et des lignes en erreur avant
confirmation, puis création en une fois via
`ingest.referentiels.creer_chantier` (même règle d'unicité, même journal
que la création manuelle) — aucune nouvelle validation métier, seulement
une boucle sur ce qui existe déjà. Seules deux erreurs bloquent une ligne :
le doublon de nom et le nom vide ; agence et client peuvent rester vides
(`creer_chantier` les stocke à `None`, aucune validation ne les exige).

**Effort indicatif.** 2 à 3 jours (lecture du fichier avec une bibliothèque
déjà répandue type `openpyxl`, écran d'aperçu/confirmation, tests).

**Prérequis.** Un exemplaire réel du fichier Excel qu'Ilane recevrait, pour
fixer les colonnes exactes et les cas d'erreur à couvrir (accents, cellules
fusionnées, lignes d'en-tête).

## b. Réactivation des contrôles de prix (R07, R08, R09)

**Besoin.** Les contrôles de prix (« Prix un peu plus cher », « Prix plus
cher que d'habitude », « Remise habituelle oubliée ») sont désactivés côté
serveur depuis le 24/09/2026 (`docs/dette.md`) : un seul mois de factures ne
permet pas d'établir un prix habituel fiable — les alertes auraient reposé
sur une référence trop courte. Dès que l'historique de factures couvre
plusieurs mois, ces trois contrôles redeviennent utiles.

**Proposition.** Aucune construction : le mécanisme existe déjà et a été
pensé pour cette réactivation — un geste d'administrateur serveur, pas un
interrupteur à l'écran. Sur le VPS, chaque instance a son propre fichier
d'environnement (`.env.prod`, `.env.demo`) : y mettre
`CONTROLE_PRIX_ACTIF=true` puis recréer le conteneur API avec
`docker compose -p habitat_<instance> --env-file .env.<instance> -f
deploy/docker-compose.yml -f deploy/docker-compose.vps.yml up -d api` (un
simple `restart` ne relit pas les variables d'environnement, il faut
recréer le conteneur). Les anomalies R07/R08/R09 déjà ouvertes avant la
désactivation n'ont jamais été fermées ni supprimées (masquées seulement) :
elles réapparaissent aussitôt, potentiellement obsolètes (basées sur un
historique d'un seul mois) — à passer en revue une fois réactivées plutôt
qu'à traiter telles quelles. Pour contrôler aussi les mois déjà écoulés (et
pas seulement les prochains dépôts), un rejeu facultatif de
`python -m app.cli rapprocher --tout` sur toutes les factures reçues
recalcule les anomalies de prix sur l'historique existant.

**Effort indicatif.** Quelques minutes (changement de variable
d'environnement et recréation du conteneur API) ; une revue des anomalies
réapparues peut prendre plus longtemps selon leur nombre.

**Prérequis.** Plusieurs mois de factures effectivement déposées et
rapprochées (le nombre minimal de références est un réglage,
`occurrences_prix_min`, modifiable dans Réglages) ; décision d'Ilane sur le
moment.

## c. Réactivation de « Livré mais pas facturé » (R06)

**Besoin.** R06 signale un article présent sur un bon de livraison déjà
rapproché d'une facture (le bloc de cette facture est au statut « reçu »)
mais absent des lignes de cette même facture, 45 jours après la date du bon
(réglage) — désactivée le 24/09/2026 (décision d'Ilane, même mécanisme que
les contrôles de prix) faute de preuve que ce cas se produise réellement
chez ce fournisseur/client. Un bon jamais facturé n'est pas couvert par ce
contrôle : R06 ne porte que sur un bon déjà rapproché d'une facture, jamais
sur un bon resté sans facture du tout. Si un cas réel est un jour constaté
(un article livré, dont la facture correspondante omet une ligne), la
question se reposera : faut-il ce contrôle en continu ?

**Proposition.** Même geste que ci-dessus : dans le fichier d'environnement
de l'instance concernée (`.env.prod` ou `.env.demo` sur le VPS),
`CONTROLE_LIVRE_NON_FACTURE_ACTIF=true`, puis recréer le conteneur API
(`docker compose -p habitat_<instance> --env-file .env.<instance> -f
deploy/docker-compose.yml -f deploy/docker-compose.vps.yml up -d api` — un
simple `restart` ne relit pas les variables d'environnement). Contrairement
aux contrôles de prix, R06 est une règle de *suivi* (contrôle différé,
évaluée une fois par jour par la commande `controles-differes`, jamais à
chaque dépôt) : réactivée, elle recommence à s'évaluer au prochain passage
de cette commande, sans rattraper rétroactivement les BL déjà en retard
avant la réactivation tant que la commande ne les revoit pas (elle les
revoit tous à chaque passage, donc dès le lendemain). Point ouvert : ce
« prochain passage » suppose que la tâche planifiée des contrôles différés
(`controles-differes`, aujourd'hui sans cron posé — `docs/dette.md`) est en
place ; tant qu'elle ne l'est pas, la réactivation seule ne suffit pas à
faire réapparaître ou recalculer R06 automatiquement.

**Effort indicatif.** Quelques minutes (changement de variable
d'environnement et recréation du conteneur API), une fois la tâche
planifiée des contrôles différés posée (point ouvert).

**Prérequis.** Un cas réel constaté par Ilane ou l'équipe (un article présent
sur un bon déjà rapproché d'une facture mais absent du détail de cette
facture, largement au-delà du délai normal de facturation du fournisseur —
pas un bon resté sans aucune facture, cas que R06 ne couvre pas) — sinon la
réactivation ne ferait que réintroduire du bruit sans valeur, la raison même
de la désactivation du 24/09/2026.

## d. Client du chantier

**Besoin.** Déjà construit le 23/09/2026 à la demande d'Ilane, en dehors du
cahier des charges d'origine : chaque chantier peut porter un client
(en plus de son agence), affiché sur sa fiche et dans le tableau de bord.
Cette section documente ce qui a été ajouté hors CDC, pour qu'Ilane sache
que ce n'est pas dans le périmètre initialement validé et puisse le
confirmer explicitement ou demander un ajustement.

**Proposition.** Rien à construire : déjà fait, déjà déployé (démo et
production). Seul le champ « client » manque encore des exports CSV
(constat SERVEUR-9, `docs/dette.md`) — à ajouter si Ilane en a besoin dans
les fichiers Excel plutôt que seulement à l'écran.

**Effort indicatif.** Un ajout du client aux exports : moins d'une demi-journée
(colonne supplémentaire dans `ingest/export.py`, même format que les colonnes
existantes).

**Prérequis.** Confirmation d'Ilane que le champ « client » correspond bien
à l'usage voulu (aujourd'hui : texte libre, aucune validation ni référentiel
de clients séparé) et, si demandé, la liste des exports concernés.

## e. Connexion Google Drive par OAuth

**Besoin.** La synchronisation Drive (`docs/refonte-front-recette.md` §6)
est bloquée depuis le lot 5 : le compte de service utilisé aujourd'hui ne
peut pas écrire sur un Drive personnel, seulement sur un Drive partagé
d'un compte Google Workspace payant. Si Habitat & Rénovation n'a pas et ne
prévoit pas de compte Google Workspace, cette voie reste fermée
indéfiniment.

**Proposition.** Basculer l'authentification Drive du compte de service vers
OAuth utilisateur (flux d'autorisation classique : l'administrateur se
connecte une fois avec son compte Google personnel ou professionnel, un
jeton de rafraîchissement est stocké côté serveur comme les autres secrets)
— fonctionne avec n'importe quel compte Google, Workspace ou non.
Changement contenu au module `jobs/drive_sync` : la synchronisation
elle-même (quoi envoyer, quand) ne change pas.

**Effort indicatif.** 2 à 4 jours (écran d'autorisation, stockage et
rafraîchissement du jeton, tests avec un compte Google réel — jamais
exercés aujourd'hui faute d'identifiants, donc une part de risque non
mesurée avant de commencer).

**Prérequis.** Décision d'Ilane : Workspace (aucune construction requise,
seulement un partage de dossier Drive) ou OAuth (ce changement) — et, pour
OAuth, un compte Google que l'administrateur accepte d'utiliser pour cette
autorisation.
