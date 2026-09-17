import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { BlDeposes } from "./pages/BlDeposes";
import { Connexion } from "./pages/Connexion";
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
          <Route path="bl" element={<BlDeposes />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
