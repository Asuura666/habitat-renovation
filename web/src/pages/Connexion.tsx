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
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="mb-6 text-xl font-semibold text-slate-900">
          Contrôle BL &amp; factures
        </h1>
        <form onSubmit={soumettre} noValidate>
          <div className="mb-4">
            <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
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
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            />
          </div>
          <div className="mb-6">
            <label
              htmlFor="mot-de-passe"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
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
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
            />
          </div>

          {connexion.isError && (
            <p role="alert" className="mb-4 text-sm text-red-700">
              {messageErreur(connexion.error)}
            </p>
          )}

          <button
            type="submit"
            disabled={connexion.isPending}
            className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {connexion.isPending ? "Connexion…" : "Se connecter"}
          </button>
        </form>
      </div>
    </main>
  );
}
