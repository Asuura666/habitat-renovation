/**
 * Ré-export (Task 4, refonte du front) : la logique de libellés et de
 * phrases chiffrées vit désormais dans `ui/libelles.ts`, seule source pour
 * les nouveaux écrans. Ce fichier ne fait plus que prêter les anciens noms
 * aux deux écrans pas encore migrés (`ATraiter`, `Anomalies`) — à retirer
 * une fois leurs imports basculés sur `ui/libelles.ts` par une tâche
 * ultérieure (spec §5). Effet de bord assumé : ces deux écrans affichent
 * désormais les mêmes titres et phrases sans jargon que le reste de
 * l'application (aucune règle métier n'est touchée, seule la présentation
 * change) ; `libelleGravite` ne reprend plus « Haute »/« Moyenne »/« Basse »
 * mais « Urgent »/« À voir »/« Info » (`Anomalies.tsx` n'est plus monté par
 * aucune route depuis cette tâche — spec §3 — donc sans effet visible tant
 * qu'il n'est pas migré ou supprimé).
 */

export type { Anomalie } from "../ui/libelles";
export {
  titreRegle as libelleRegle,
  urgence as libelleGravite,
  phraseProbleme as justification,
} from "../ui/libelles";
