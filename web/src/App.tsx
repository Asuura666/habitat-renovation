import type { ReactElement } from "react";
import { Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { Anomalies } from "./pages/Anomalies";
import { ATraiter } from "./pages/ATraiter";
import {
  BilanChantiersFournisseur,
  BilanFournisseursGlobal,
} from "./pages/BilanFournisseur";
import { BlDeposes } from "./pages/BlDeposes";
import { ChantiersListe } from "./pages/ChantiersListe";
import { Connexion } from "./pages/Connexion";
import { DocumentDetail } from "./pages/DocumentDetail";
import { FactureDetail } from "./pages/FactureDetail";
import { FacturesListe } from "./pages/FacturesListe";
import { FicheChantier } from "./pages/FicheChantier";
import { Journal } from "./pages/Journal";
import { Reglages } from "./pages/Reglages";
import { GardeAdmin } from "./routes/GardeAdmin";
import { RedirectionAccueil } from "./routes/RedirectionAccueil";
import { RedirectionAncienneUrl } from "./routes/RedirectionAncienneUrl";
import { RouteProtegee } from "./routes/RouteProtegee";

export function App(): ReactElement {
  return (
    <>
      <EcouteAuthentification />
      <Routes>
        <Route path="/connexion" element={<Connexion />} />
        <Route
          path="/"
          element={
            <RouteProtegee>
              <Gabarit />
            </RouteProtegee>
          }
        >
          {/* Vue d'ensemble (admin) — Task 4 y pose `EcranEnConstruction`,
              une tâche suivante la remplace (voir RedirectionAccueil.tsx).
              `GardeAdmin` y renvoie déjà l'agent vers `/documents`. */}
          <Route
            index
            element={
              <GardeAdmin>
                <RedirectionAccueil />
              </GardeAdmin>
            }
          />

          {/* À régler (remplace « À traiter »/« Anomalies ») — écran
              existant `ATraiter` conservé tel quel (habillage seulement, la
              Task 6 le remplace). */}
          <Route
            path="a-regler"
            element={
              <GardeAdmin>
                <ATraiter />
              </GardeAdmin>
            }
          />

          {/* Chantiers (remplace « Bilan ») — Task 7 : `ChantiersListe`
              (liste, filtres, création, bandeau chantiers silencieux) et
              `FicheChantier` (fiche, toutes les livraisons du chantier,
              édition, problèmes ouverts) reprennent tout le contenu utile
              des anciens écrans `Bilan`/`Chantiers`/`BilanFournisseur`
              (référentiel + validation d'alias : la validation d'alias est
              reprise par l'écran « À régler », Task 6 ; les agences d'un
              fournisseur par la fiche fournisseur, Task 9). `chantiers
              /referentiel` (ex-écran « Chantiers & fournisseurs ») et
              `chantiers/:chantierId/:fournisseurId` (ex-détail des BL d'un
              couple chantier/fournisseur, `BilanBl`) sont désormais de
              simples redirections vers `/chantiers` et `/chantiers/:c` — le
              lien « Gérer les chantiers » de la barre latérale
              (Gabarit.tsx) reste valide. Route statique déclarée avant
              `chantiers/:chantierId` pour ne jamais être lue comme un
              identifiant de chantier. */}
          <Route
            path="chantiers"
            element={
              <GardeAdmin>
                <ChantiersListe />
              </GardeAdmin>
            }
          />
          <Route
            path="chantiers/referentiel"
            element={<RedirectionAncienneUrl vers={() => "/chantiers"} />}
          />
          <Route
            path="chantiers/:chantierId"
            element={
              <GardeAdmin>
                <FicheChantier />
              </GardeAdmin>
            }
          />
          <Route
            path="chantiers/:chantierId/:fournisseurId"
            element={
              <RedirectionAncienneUrl vers={(p) => `/chantiers/${p.chantierId ?? ""}`} />
            }
          />

          {/* Fournisseurs (remplace « Bilan par fournisseur ») — écrans
              existants conservés, la Task 8 les remplace. */}
          <Route
            path="fournisseurs"
            element={
              <GardeAdmin>
                <BilanFournisseursGlobal />
              </GardeAdmin>
            }
          />
          <Route
            path="fournisseurs/:fournisseurId"
            element={
              <GardeAdmin>
                <BilanChantiersFournisseur />
              </GardeAdmin>
            }
          />

          {/* Documents (remplace « Factures »/« BL déposés ») — admin (tous)
              et agent (ses dépôts, lecture seule) : aucune `GardeAdmin` ici,
              comme avant Task 4. `documents/:id` et `bl/:id` montent le même
              écran existant `DocumentDetail` (L3-D19) — la Task 9 remplace
              la liste, la Task 5 la fiche BL. */}
          <Route path="documents" element={<BlDeposes />} />
          <Route path="documents/:id" element={<DocumentDetail />} />
          <Route path="bl/:id" element={<DocumentDetail />} />

          <Route
            path="journal"
            element={
              <GardeAdmin>
                <Journal />
              </GardeAdmin>
            }
          />
          <Route
            path="reglages"
            element={
              <GardeAdmin>
                <Reglages />
              </GardeAdmin>
            }
          />

          {/* Écrans sans remplacement construit — fix round 1 R1 (« aucune
              fonctionnalité existante n'est supprimée » l'emporte sur la
              redirection posée par erreur en Task 4) : restent MONTÉS sur
              leur ancienne URL, pas de redirection, jusqu'à ce qu'une tâche
              suivante les migre (Task 9 pour Factures, Task 6 pour
              Anomalies). */}
          <Route
            path="factures"
            element={
              <GardeAdmin>
                <FacturesListe />
              </GardeAdmin>
            }
          />
          <Route
            path="factures/:id"
            element={
              <GardeAdmin>
                <FactureDetail />
              </GardeAdmin>
            }
          />
          <Route
            path="anomalies"
            element={
              <GardeAdmin>
                <Anomalies />
              </GardeAdmin>
            }
          />

          {/* --------------------------------------------------------------
              Anciennes URL → nouvelles (spec §3, fix round 1 R1/R2) : un
              seul composant partagé pour toutes les redirections, qui
              reporte toujours les paramètres de recherche et l'ancre de
              l'URL d'origine (voir web/src/routes/).
              -------------------------------------------------------------- */}
          <Route path="a-traiter" element={<RedirectionAncienneUrl vers={() => "/a-regler"} />} />
          <Route path="bilan" element={<RedirectionAncienneUrl vers={() => "/chantiers"} />} />
          <Route
            path="bilan/fournisseurs"
            element={<RedirectionAncienneUrl vers={() => "/fournisseurs"} />}
          />
          <Route
            path="bilan/fournisseurs/:fournisseurId"
            element={
              <RedirectionAncienneUrl vers={(p) => `/fournisseurs/${p.fournisseurId ?? ""}`} />
            }
          />
          <Route
            path="bilan/:chantierId"
            element={<RedirectionAncienneUrl vers={(p) => `/chantiers/${p.chantierId ?? ""}`} />}
          />
          <Route
            path="bilan/:chantierId/:fournisseurId"
            element={
              <RedirectionAncienneUrl
                vers={(p) => `/chantiers/${p.chantierId ?? ""}/${p.fournisseurId ?? ""}`}
              />
            }
          />
          <Route path="bl" element={<RedirectionAncienneUrl vers={() => "/documents"} />} />

          <Route path="*" element={<RedirectionAncienneUrl vers={() => "/"} />} />
        </Route>
      </Routes>
    </>
  );
}
