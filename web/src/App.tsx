import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { Anomalies } from "./pages/Anomalies";
import { ATraiter } from "./pages/ATraiter";
import { Bilan } from "./pages/Bilan";
import {
  BilanBl,
  BilanChantiersFournisseur,
  BilanFournisseursChantier,
  BilanFournisseursGlobal,
} from "./pages/BilanFournisseur";
import { BlDeposes } from "./pages/BlDeposes";
import { Connexion } from "./pages/Connexion";
import { DocumentDetail } from "./pages/DocumentDetail";
import { FactureDetail } from "./pages/FactureDetail";
import { FacturesListe } from "./pages/FacturesListe";
import { GardeAdmin } from "./routes/GardeAdmin";
import { RedirectionAccueil } from "./routes/RedirectionAccueil";
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
          <Route index element={<RedirectionAccueil />} />
          <Route
            path="a-traiter"
            element={
              <GardeAdmin>
                <ATraiter />
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
            path="bilan"
            element={
              <GardeAdmin>
                <Bilan />
              </GardeAdmin>
            }
          />
          <Route
            path="bilan/fournisseurs"
            element={<GardeAdmin><BilanFournisseursGlobal /></GardeAdmin>}
          />
          <Route
            path="bilan/fournisseurs/:fournisseurId"
            element={<GardeAdmin><BilanChantiersFournisseur /></GardeAdmin>}
          />
          <Route
            path="bilan/:chantierId"
            element={<GardeAdmin><BilanFournisseursChantier /></GardeAdmin>}
          />
          <Route
            path="bilan/:chantierId/:fournisseurId"
            element={<GardeAdmin><BilanBl /></GardeAdmin>}
          />
          <Route path="bl" element={<BlDeposes />} />
          {/* Admin (tous) et agent (ses dépôts, lecture seule) — L3-D19 :
              aucune `GardeAdmin` ici, `donnees.modifiable` décide seul de
              l'affichage des contrôles d'édition (voir DocumentDetail.tsx). */}
          <Route path="documents/:id" element={<DocumentDetail />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
