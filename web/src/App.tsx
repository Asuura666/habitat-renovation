import type { ReactElement } from "react";
import { Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { Connexion } from "./pages/Connexion";
import { RouteProtegee } from "./routes/RouteProtegee";

export function App(): ReactElement {
  return (
    <>
      <EcouteAuthentification />
      <Routes>
        <Route path="/connexion" element={<Connexion />} />
        <Route
          path="/*"
          element={
            <RouteProtegee>
              <Gabarit />
            </RouteProtegee>
          }
        />
      </Routes>
    </>
  );
}
