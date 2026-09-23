import type { ReactElement } from "react";
import { Navigate, Route, Routes, useParams } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { ATraiter } from "./pages/ATraiter";
import { Bilan } from "./pages/Bilan";
import {
  BilanChantiersFournisseur,
  BilanFournisseursChantier,
  BilanFournisseursGlobal,
} from "./pages/BilanFournisseur";
import { BlDeposes } from "./pages/BlDeposes";
import { Connexion } from "./pages/Connexion";
import { DocumentDetail } from "./pages/DocumentDetail";
import { Journal } from "./pages/Journal";
import { Reglages } from "./pages/Reglages";
import { GardeAdmin } from "./routes/GardeAdmin";
import { RedirectionAccueil } from "./routes/RedirectionAccueil";
import { RouteProtegee } from "./routes/RouteProtegee";

// --------------------------------------------------------------------------
// Anciennes URL (Telegram, favoris) : redirigées vers les nouvelles (Task 4,
// spec §3). Les trois ci-dessous portent un paramètre qu'il faut reporter
// dans la nouvelle URL — `<Navigate to="...">` seul ne peut pas lire
// `useParams`, d'où ces petits composants dédiés.
// --------------------------------------------------------------------------

function VersChantier(): ReactElement {
  const { chantierId } = useParams<{ chantierId: string }>();
  return <Navigate to={`/chantiers/${chantierId ?? ""}`} replace />;
}

function VersFournisseur(): ReactElement {
  const { fournisseurId } = useParams<{ fournisseurId: string }>();
  return <Navigate to={`/fournisseurs/${fournisseurId ?? ""}`} replace />;
}

function VersDocument(): ReactElement {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/documents/${id ?? ""}`} replace />;
}

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

          {/* Chantiers (remplace « Bilan ») — écrans existants conservés :
              `Bilan` pour la liste, `BilanFournisseursChantier` (ex.
              `bilan/:chantierId`) pour la fiche — la Task 7 les remplace. */}
          <Route
            path="chantiers"
            element={
              <GardeAdmin>
                <Bilan />
              </GardeAdmin>
            }
          />
          <Route
            path="chantiers/:chantierId"
            element={
              <GardeAdmin>
                <BilanFournisseursChantier />
              </GardeAdmin>
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

          {/* --------------------------------------------------------------
              Anciennes routes → nouvelles (spec §3). Aucune fonctionnalité
              supprimée : les écrans qu'elles montaient (`Anomalies`,
              `FacturesListe`, `FactureDetail`, `BilanBl`) restent dans le
              dépôt, simplement plus montés par aucune route — une tâche
              suivante les migre ou les retire.
              -------------------------------------------------------------- */}
          <Route path="a-traiter" element={<Navigate to="/a-regler" replace />} />
          <Route path="anomalies" element={<Navigate to="/a-regler" replace />} />
          <Route path="bilan" element={<Navigate to="/chantiers" replace />} />
          <Route path="bilan/fournisseurs" element={<Navigate to="/fournisseurs" replace />} />
          <Route path="bilan/fournisseurs/:fournisseurId" element={<VersFournisseur />} />
          <Route path="bilan/:chantierId" element={<VersChantier />} />
          <Route path="bilan/:chantierId/:fournisseurId" element={<VersChantier />} />
          <Route path="factures" element={<Navigate to="/documents" replace />} />
          <Route path="factures/:id" element={<VersDocument />} />
          <Route path="bl" element={<Navigate to="/documents" replace />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  );
}
