# tests/fixtures/

Ce dossier contient des documents réels du client (factures PDF, photos de
bons de livraison) utilisés par certains tests pour comparer des comptes et
des écarts.

Règles :

- Aucun fichier de ce dossier, à l'exception de ce `README.md`, n'est suivi
  par git (`.gitignore`) ni commité. Un hook `pre-commit` local refuse en
  plus tout ajout forcé.
- Le contenu des fixtures (noms, chantiers, numéros, montants) n'apparaît
  jamais dans le code, un message de commit, un log ou un message
  d'assertion. Les tests commités utilisent des données inventées.
- Les tests qui dépendent d'une fixture réelle absente (ex. clone neuf) sont
  marqués `skip` avec la raison explicite ; ce n'est jamais un échec
  silencieux.
