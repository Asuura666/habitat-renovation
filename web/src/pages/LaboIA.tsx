import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErreurApi } from "../api/client";
import {
  CLE_DERNIERS_ESSAIS_LABO,
  CLE_ETAT_LABO,
  CLE_JOURNAL_APPELS_LABO,
  cleEssaiLabo,
  lancerEssaiExplicationLabo,
  lancerEssaiPrixLabo,
  lancerEssaiSyntheseLabo,
  lireEssaiLabo,
  lireEtatLabo,
  listerDerniersEssaisLabo,
  listerJournalAppelsLabo,
  type TraceEssai,
} from "../api/ia";
import { listerAlertesPrix } from "../api/prix";
import { TIRET } from "../lib/formats";
import { Bouton, Carte, EnTetePage, EtatVide } from "../ui";

const CLE_ALERTES_PRIX_LABO = ["ia", "labo", "alertes-prix"] as const;

const LIBELLES_TYPE_ESSAI: Record<string, string> = {
  prix: "Prix internet",
  explication: "Explication",
  synthese: "Synthèse",
};

const CHAMP_CLASSE =
  "mt-1 block min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const ETIQUETTE_CLASSE = "block text-sm text-encre-2";

function messageErreur(erreur: unknown): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return "L'essai n'a pas pu être lancé.";
}

function Voyant({ ok, texte }: { ok: boolean; texte: string }): ReactElement {
  return (
    <p className="flex items-center gap-2 text-sm text-encre">
      <span
        aria-hidden="true"
        className={`h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-conforme" : "bg-alerte"}`}
      />
      {texte}
    </p>
  );
}

function StatutBadge({ statut }: { statut: TraceEssai["statut"] }): ReactElement {
  const libelle = statut === "en_cours" ? "En cours…" : statut === "fini" ? "Terminé" : "Erreur";
  const classe =
    statut === "fini" ? "text-conforme" : statut === "erreur" ? "text-alerte" : "text-encre-2";
  return <span className={`text-sm font-medium ${classe}`}>{libelle}</span>;
}

/**
 * État de l'IA (brief LABO §1) : une ligne par point avec voyant, et ce
 * qu'il faut faire si l'abonnement n'est pas connecté.
 */
function EtatIA(): ReactElement {
  const etat = useQuery({ queryKey: CLE_ETAT_LABO, queryFn: lireEtatLabo, refetchInterval: 30_000 });

  return (
    <Carte titre="État de l'IA">
      {etat.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Vérification en cours…
        </p>
      )}
      {etat.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de vérifier l'état de l'IA.
        </p>
      )}
      {etat.data && (
        <div className="space-y-2">
          <Voyant
            ok={etat.data.ia_active}
            texte={etat.data.ia_active ? "IA allumée sur cette instance" : "IA éteinte sur cette instance"}
          />
          {etat.data.ia_active && (
            <>
              <Voyant
                ok={etat.data.joignable}
                texte={
                  etat.data.joignable
                    ? "OpenCode joignable"
                    : `OpenCode injoignable (${etat.data.joignable_detail ?? "raison inconnue"})`
                }
              />
              <Voyant
                ok={etat.data.agents.length === 3}
                texte={
                  etat.data.agents.length === 3
                    ? "Les trois agents sont présents"
                    : `Agents présents : ${etat.data.agents.length > 0 ? etat.data.agents.join(", ") : "aucun"}`
                }
              />
              <Voyant
                ok={etat.data.abonnement_connecte}
                texte={
                  etat.data.abonnement_connecte
                    ? "Abonnement ChatGPT connecté"
                    : "Abonnement ChatGPT non connecté"
                }
              />
              {!etat.data.abonnement_connecte && (
                <p className="ml-5 text-sm text-encre-2">
                  Lancer la connexion : voir docs/phase-4-ia.md §3.1 — copier :{" "}
                  <code className="rounded bg-fond px-1 py-0.5 text-xs">
                    docker compose -f deploy/opencode/docker-compose.yml run --rm opencode opencode auth login
                  </code>
                </p>
              )}
              <Voyant
                ok={etat.data.recherche_web}
                texte={etat.data.recherche_web ? "Recherche web disponible" : "Recherche web indisponible"}
              />
            </>
          )}
          <p className="text-sm text-encre-2">
            Appels aujourd'hui : {etat.data.appels_aujourdhui} / {etat.data.appels_max_jour}
          </p>
        </div>
      )}
    </Carte>
  );
}

function FormulairePrix({ onLance }: { onLance: (id: string) => void }): ReactElement {
  const [fournisseur, setFournisseur] = useState("");
  const [designation, setDesignation] = useState("");
  const [code, setCode] = useState("");
  const [unite, setUnite] = useState("");
  const lancement = useMutation({
    mutationFn: () =>
      lancerEssaiPrixLabo({
        fournisseur: fournisseur.trim() === "" ? undefined : fournisseur.trim(),
        designation: designation.trim(),
        code: code.trim() === "" ? undefined : code.trim(),
        unite: unite.trim() === "" ? undefined : unite.trim(),
      }),
    onSuccess: (reponse) => onLance(reponse.id),
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    lancement.mutate();
  }

  return (
    <form onSubmit={soumettre} className="space-y-3 border-t border-bordure pt-4 first:border-t-0 first:pt-0">
      <h3 className="font-medium text-encre">Prix internet</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={ETIQUETTE_CLASSE}>
          Fournisseur
          <input
            value={fournisseur}
            onChange={(evenement) => setFournisseur(evenement.target.value)}
            className={CHAMP_CLASSE}
          />
        </label>
        <label className={ETIQUETTE_CLASSE}>
          Désignation
          <input
            required
            value={designation}
            onChange={(evenement) => setDesignation(evenement.target.value)}
            className={CHAMP_CLASSE}
          />
        </label>
        <label className={ETIQUETTE_CLASSE}>
          Référence
          <input value={code} onChange={(evenement) => setCode(evenement.target.value)} className={CHAMP_CLASSE} />
        </label>
        <label className={ETIQUETTE_CLASSE}>
          Unité
          <input value={unite} onChange={(evenement) => setUnite(evenement.target.value)} className={CHAMP_CLASSE} />
        </label>
      </div>
      {lancement.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreur(lancement.error)}
        </p>
      )}
      <Bouton type="submit" disabled={lancement.isPending || designation.trim() === ""}>
        {lancement.isPending ? "Lancement…" : "Lancer l'essai"}
      </Bouton>
    </form>
  );
}

function FormulaireExplication({ onLance }: { onLance: (id: string) => void }): ReactElement {
  const alertes = useQuery({ queryKey: CLE_ALERTES_PRIX_LABO, queryFn: () => listerAlertesPrix() });
  const [anomalieId, setAnomalieId] = useState("");
  const lancement = useMutation({
    mutationFn: () => lancerEssaiExplicationLabo(anomalieId),
    onSuccess: (reponse) => onLance(reponse.id),
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    lancement.mutate();
  }

  const options = (alertes.data ?? []).flatMap((alerte) =>
    alerte.anomalie_ids.map((id) => ({
      id,
      libelle: `${alerte.produit} — ${alerte.fournisseur} (${alerte.date_bon})`,
    })),
  );

  return (
    <form onSubmit={soumettre} className="space-y-3 border-t border-bordure pt-4">
      <h3 className="font-medium text-encre">Explication d'une alerte prix</h3>
      {alertes.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement des alertes…
        </p>
      )}
      {alertes.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les alertes prix.
        </p>
      )}
      {alertes.data && options.length === 0 && (
        <EtatVide message="Aucune alerte prix ouverte pour l'instant." />
      )}
      {options.length > 0 && (
        <label className={ETIQUETTE_CLASSE}>
          Alerte à expliquer
          <select
            required
            value={anomalieId}
            onChange={(evenement) => setAnomalieId(evenement.target.value)}
            className={CHAMP_CLASSE}
          >
            <option value="">Choisir une alerte…</option>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.libelle}
              </option>
            ))}
          </select>
        </label>
      )}
      {lancement.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreur(lancement.error)}
        </p>
      )}
      <Bouton type="submit" disabled={lancement.isPending || anomalieId === ""}>
        {lancement.isPending ? "Lancement…" : "Lancer l'essai"}
      </Bouton>
    </form>
  );
}

function FormulaireSynthese({ onLance }: { onLance: (id: string) => void }): ReactElement {
  const [semaineDebut, setSemaineDebut] = useState("");
  const lancement = useMutation({
    mutationFn: () => lancerEssaiSyntheseLabo(semaineDebut),
    onSuccess: (reponse) => onLance(reponse.id),
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    lancement.mutate();
  }

  return (
    <form onSubmit={soumettre} className="space-y-3 border-t border-bordure pt-4">
      <h3 className="font-medium text-encre">Synthèse hebdomadaire des commentaires</h3>
      <label className={ETIQUETTE_CLASSE}>
        Date du lundi de la semaine
        <input
          type="date"
          required
          value={semaineDebut}
          onChange={(evenement) => setSemaineDebut(evenement.target.value)}
          className={CHAMP_CLASSE}
        />
      </label>
      {lancement.isError && (
        <p role="alert" className="text-sm text-alerte">
          {messageErreur(lancement.error)}
        </p>
      )}
      <Bouton type="submit" disabled={lancement.isPending || semaineDebut === ""}>
        {lancement.isPending ? "Lancement…" : "Lancer l'essai"}
      </Bouton>
    </form>
  );
}

function Essayer({ onLance }: { onLance: (id: string) => void }): ReactElement {
  return (
    <Carte titre="Essayer">
      <p className="mb-4 rounded-lg bg-fond p-3 text-sm text-encre-2">
        Essai : rien n'est enregistré, mais l'appel compte dans le plafond du jour.
      </p>
      <div className="space-y-6">
        <FormulairePrix onLance={onLance} />
        <FormulaireExplication onLance={onLance} />
        <FormulaireSynthese onLance={onLance} />
      </div>
    </Carte>
  );
}

function ResultatEssai({
  type,
  resultat,
}: {
  type: TraceEssai["type"];
  resultat: Record<string, unknown>;
}): ReactElement {
  if (type === "explication") {
    return <p className="text-sm text-encre">{typeof resultat.texte === "string" ? resultat.texte : ""}</p>;
  }
  if (type === "prix") {
    if (resultat.statut === "trouve") {
      const sourceUrl = typeof resultat.source_url === "string" ? resultat.source_url : null;
      return (
        <p className="text-sm text-encre">
          {`Prix trouvé : ${String(resultat.prix)} ${typeof resultat.devise === "string" ? resultat.devise : ""} ${
            typeof resultat.taxes === "string" ? resultat.taxes : ""
          }`}
          {sourceUrl !== null && sourceUrl.startsWith("https://") && (
            <>
              {" — "}
              <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                voir la source
              </a>
            </>
          )}
        </p>
      );
    }
    return (
      <p className="text-sm text-encre-2">
        Prix non vérifiable : {typeof resultat.raison === "string" ? resultat.raison : "raison inconnue"}
      </p>
    );
  }
  // synthese
  const actions = Array.isArray(resultat.actions)
    ? (resultat.actions as { texte: string; commentaires: string[] }[])
    : [];
  return (
    <div className="space-y-2 text-sm text-encre">
      <p>{typeof resultat.resume === "string" ? resultat.resume : ""}</p>
      {actions.length > 0 && (
        <ul className="list-disc space-y-1 pl-5">
          {actions.map((action, indice) => (
            <li key={indice}>{action.texte}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DerouleContenu({ trace }: { trace: TraceEssai }): ReactElement {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <StatutBadge statut={trace.statut} />
        {trace.duree_ms !== null && (
          <span className="text-sm text-encre-2">{(trace.duree_ms / 1000).toFixed(1)} s</span>
        )}
        {trace.modele !== null && <span className="text-sm text-encre-2">Modèle : {trace.modele}</span>}
        {trace.appels_restants !== null && (
          <span className="text-sm text-encre-2">{trace.appels_restants} appel(s) restant(s) aujourd'hui</span>
        )}
      </div>

      {trace.erreur !== null && (
        <div role="alert" className="rounded-lg border border-alerte bg-fond p-3 text-sm text-alerte">
          <p>{typeof trace.erreur.message_court === "string" ? trace.erreur.message_court : "Échec de l'essai."}</p>
          {trace.erreur.brut !== null && trace.erreur.brut !== undefined && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs">Détail brut</summary>
              <pre className="mt-1 max-h-60 overflow-x-auto whitespace-pre-wrap text-xs">
                {JSON.stringify(trace.erreur.brut, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      <details className="border-t border-bordure pt-3">
        <summary className="cursor-pointer text-sm font-semibold text-encre">① Texte envoyé</summary>
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-fond p-3 font-mono text-xs text-encre">
          {trace.texte_envoye}
        </pre>
      </details>

      <div className="border-t border-bordure pt-3">
        <p className="text-sm font-semibold text-encre">② Recherches et pages ouvertes</p>
        {trace.outils.length === 0 && (
          <p className="mt-1 text-sm text-encre-2">Aucune recherche ni page ouverte.</p>
        )}
        <ul className="mt-2 space-y-2">
          {trace.outils.map((outil, indice) => (
            <li key={indice} className="rounded-lg border border-bordure p-2 text-sm">
              <p className="font-medium text-encre">
                {outil.outil === "webfetch" ? "Page ouverte : " : "Recherche : "}
                {outil.outil === "webfetch" && outil.adresse.startsWith("https://") ? (
                  <a
                    href={outil.adresse}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    {outil.adresse}
                  </a>
                ) : (
                  outil.adresse
                )}
              </p>
              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-encre-2">Extrait</summary>
                <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap text-xs">{outil.extrait}</pre>
              </details>
            </li>
          ))}
        </ul>
      </div>

      <details className="border-t border-bordure pt-3">
        <summary className="cursor-pointer text-sm font-semibold text-encre">③ Réponse brute</summary>
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-fond p-3 font-mono text-xs text-encre">
          {JSON.stringify(trace.reponse_brute, null, 2)}
        </pre>
      </details>

      <div className="border-t border-bordure pt-3">
        <p className="text-sm font-semibold text-encre">④ Contrôles</p>
        <ul className="mt-2 space-y-1">
          {trace.controles.map((controle, indice) => (
            <li key={indice} className="flex items-start gap-2 text-sm">
              <span aria-hidden="true" className={controle.ok ? "text-conforme" : "text-alerte"}>
                {controle.ok ? "✓" : "✗"}
              </span>
              <span className="text-encre">
                <span className="font-medium">{controle.nom}</span> — {controle.detail}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-bordure pt-3">
        <p className="text-sm font-semibold text-encre">⑤ Résultat</p>
        {trace.resultat === null && (
          <p className="mt-1 text-sm text-encre-2">Aucun résultat (essai en cours ou en échec).</p>
        )}
        {trace.resultat !== null && (
          <div className="mt-1">
            <ResultatEssai type={trace.type} resultat={trace.resultat as Record<string, unknown>} />
          </div>
        )}
      </div>
    </div>
  );
}

function Deroule({ essaiId }: { essaiId: string | null }): ReactElement {
  const essai = useQuery({
    queryKey: cleEssaiLabo(essaiId ?? "aucun"),
    queryFn: () => lireEssaiLabo(essaiId as string),
    enabled: essaiId !== null,
    refetchInterval: (requete) => (requete.state.data?.statut === "en_cours" ? 2000 : false),
  });

  return (
    <Carte titre="Déroulé de l'essai" className="overflow-x-auto">
      {essaiId === null && (
        <EtatVide message="Lancez un essai, ou choisissez-en un dans la liste ci-dessous." />
      )}
      {essaiId !== null && essai.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {essaiId !== null && essai.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger cet essai.
        </p>
      )}
      {essaiId !== null && essai.data && <DerouleContenu trace={essai.data} />}
    </Carte>
  );
}

function DerniersEssais({
  essaiSelectionne,
  onSelectionner,
}: {
  essaiSelectionne: string | null;
  onSelectionner: (id: string) => void;
}): ReactElement {
  const essais = useQuery({
    queryKey: CLE_DERNIERS_ESSAIS_LABO,
    queryFn: listerDerniersEssaisLabo,
    refetchInterval: 5000,
  });

  return (
    <Carte titre="Derniers essais">
      {essais.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {essais.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les essais.
        </p>
      )}
      {essais.data && essais.data.length === 0 && (
        <EtatVide message="Aucun essai depuis le démarrage du serveur." />
      )}
      {essais.data && essais.data.length > 0 && (
        <ul className="divide-y divide-bordure">
          {essais.data.map((resume) => (
            <li key={resume.id}>
              <button
                type="button"
                onClick={() => onSelectionner(resume.id)}
                className={`flex min-h-[44px] w-full items-center justify-between gap-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  essaiSelectionne === resume.id ? "font-semibold text-accent" : "text-encre"
                }`}
              >
                <span className="text-sm">{LIBELLES_TYPE_ESSAI[resume.type] ?? resume.type}</span>
                <StatutBadge statut={resume.statut} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Carte>
  );
}

function JournalAppels(): ReactElement {
  const journal = useQuery({
    queryKey: CLE_JOURNAL_APPELS_LABO,
    queryFn: listerJournalAppelsLabo,
    refetchInterval: 10_000,
  });

  return (
    <Carte titre="Journal des appels" className="overflow-x-auto">
      {journal.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {journal.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger le journal.
        </p>
      )}
      {journal.data && journal.data.length === 0 && <EtatVide message="Aucun appel à l'IA pour l'instant." />}
      {journal.data && journal.data.length > 0 && (
        <table className="min-w-full text-left text-sm">
          <thead>
            <tr className="text-encre-2">
              <th className="pb-2 pr-4 font-medium">Heure</th>
              <th className="pb-2 pr-4 font-medium">Type</th>
              <th className="pb-2 pr-4 font-medium">Résultat</th>
              <th className="pb-2 pr-4 font-medium">Erreur</th>
              <th className="pb-2 font-medium">Durée</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {journal.data.map((ligne) => (
              <tr key={ligne.id}>
                <td className="py-2 pr-4 text-encre">{new Date(ligne.created_at).toLocaleString("fr-FR")}</td>
                <td className="py-2 pr-4 text-encre">{LIBELLES_TYPE_ESSAI[ligne.usage] ?? ligne.usage}</td>
                <td className="py-2 pr-4 text-encre">{ligne.statut === "ok" ? "Réussi" : "Échoué"}</td>
                <td className="py-2 pr-4 text-encre-2">{ligne.erreur ?? TIRET}</td>
                <td className="py-2 text-encre">{ligne.duree_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Carte>
  );
}

/**
 * Écran « Laboratoire IA » (brief LABO, admin) : teste les fonctions de l'IA
 * avant de s'y fier, en montrant exactement ce qui se passe (texte envoyé,
 * recherches/pages ouvertes, réponse brute, contrôles anti-invention,
 * résultat) plutôt que de se contenter d'un résultat final. Un essai
 * n'enregistre rien (`ingest.ia_labo`), perdu au redémarrage du serveur
 * (mémoire du processus).
 */
export function LaboIA(): ReactElement {
  const [essaiId, setEssaiId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  function surLancement(id: string): void {
    setEssaiId(id);
    void queryClient.invalidateQueries({ queryKey: CLE_DERNIERS_ESSAIS_LABO });
  }

  return (
    <div className="max-w-4xl space-y-6">
      <EnTetePage titre="Laboratoire IA" surtitre="Essai réservé aux administrateurs, rien n'est enregistré" />
      <EtatIA />
      <Essayer onLance={surLancement} />
      <Deroule essaiId={essaiId} />
      <DerniersEssais essaiSelectionne={essaiId} onSelectionner={setEssaiId} />
      <JournalAppels />
    </div>
  );
}
