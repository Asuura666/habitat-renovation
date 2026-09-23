import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { appelerApi, ErreurApi } from "../api/client";
import { CLE_MOI } from "../api/moi";

function messageErreur(erreur: unknown): string {
  if (erreur instanceof ErreurApi) {
    if (erreur.status === 400) {
      return "Email ou mot de passe incorrect.";
    }
    if (erreur.status === 429) {
      return "Trop de tentatives, réessayez dans une minute.";
    }
  }
  return "Une erreur est survenue, réessayez.";
}

const CLASSES_CHAMP =
  "w-full rounded-lg border border-bordure bg-surface px-3 py-2.5 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-sm font-medium text-encre";

/** Carte centrée sur fond ivoire, titre Fraunces — même charte que le reste
 * de l'application (Task 4, habillage seulement : logique de connexion
 * inchangée). */
export function Connexion(): ReactElement {
  const [email, setEmail] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const connexion = useMutation({
    mutationFn: async () => {
      const corps = new URLSearchParams({ username: email, password: motDePasse });
      await appelerApi("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: corps,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_MOI });
      navigate("/", { replace: true });
    },
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    connexion.mutate();
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-fond px-4 font-sans text-encre">
      <div className="w-full max-w-sm rounded-carte border border-bordure bg-surface p-8 shadow-sm">
        <p className="mb-1 text-xs text-encre-2">Contrôle des livraisons</p>
        <h1 className="mb-6 font-titre text-2xl font-semibold text-accent">
          Habitat &amp; Rénovation
        </h1>
        <form onSubmit={soumettre} noValidate>
          <div className="mb-4">
            <label htmlFor="email" className={CLASSES_LABEL}>
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(evenement) => setEmail(evenement.target.value)}
              className={CLASSES_CHAMP}
            />
          </div>
          <div className="mb-6">
            <label htmlFor="mot-de-passe" className={CLASSES_LABEL}>
              Mot de passe
            </label>
            <input
              id="mot-de-passe"
              name="mot-de-passe"
              type="password"
              autoComplete="current-password"
              required
              value={motDePasse}
              onChange={(evenement) => setMotDePasse(evenement.target.value)}
              className={CLASSES_CHAMP}
            />
          </div>

          {connexion.isError && (
            <p role="alert" className="mb-4 text-sm text-alerte">
              {messageErreur(connexion.error)}
            </p>
          )}

          <button
            type="submit"
            disabled={connexion.isPending}
            className="min-h-[44px] w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {connexion.isPending ? "Connexion…" : "Se connecter"}
          </button>
        </form>
      </div>
    </main>
  );
}
