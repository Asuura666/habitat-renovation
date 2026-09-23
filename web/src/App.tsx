import type { ReactElement } from "react";
import { Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { ARegler } from "./pages/ARegler";
import { Bilan } from "./pages/Bilan";
import {
  BilanBl,
  BilanChantiersFournisseur,
  BilanFournisseursChantier,
  BilanFournisseursGlobal,
} from "./pages/BilanFournisseur";
import { BlDeposes } from "./pages/BlDeposes";
import { Chantiers } from "./pages/Chantiers";
import { Connexion } from "./pages/Connexion";
import { DocumentDetail } from "./pages/DocumentDetail";
import { FactureDetail } from "./pages/FactureDetail";
import { FacturesListe } from "./pages/FacturesListe";
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

          {/* À régler (remplace « À traiter »/« Anomalies », Task 6) :
              file unique des anomalies ouvertes et du contenu de
              `GET /api/a-traiter` (documents à vérifier, alias, articles).
              `ARegler.tsx` lit `useParams().id` lui-même (`undefined` sur
              la route sans `:id`) pour afficher, en plus de la liste, un
              panneau de détail en `lg+` ou une page plein écran en
              dessous — les deux routes montent donc le même composant. */}
          <Route
            path="a-regler"
            element={
              <GardeAdmin>
                <ARegler />
              </GardeAdmin>
            }
          />
          <Route
            path="a-regler/:id"
            element={
              <GardeAdmin>
                <ARegler />
              </GardeAdmin>
            }
          />

          {/* Chantiers (remplace « Bilan ») — écrans existants conservés :
              `Bilan` pour la liste, `BilanFournisseursChantier` (ex.
              `bilan/:chantierId`) pour la fiche, `BilanBl` (ex.
              `bilan/:chantierId/:fournisseurId`, fix round 1 R2) pour le
              détail des BL d'un couple chantier/fournisseur — la Task 7 les
              remplace. `chantiers/referentiel` (fix round 1 R1) garde
              accessible l'écran de création de chantier et de validation
              d'alias (ex-« Chantiers & fournisseurs », L5-T8) tant qu'il
              n'a pas été repris par la fiche chantier de la Task 7 — lien
              « Gérer les chantiers » dans la barre latérale (Gabarit.tsx).
              Route statique déclarée avant `chantiers/:chantierId` pour ne
              jamais être lue comme un identifiant de chantier. */}
          <Route
            path="chantiers"
            element={
              <GardeAdmin>
                <Bilan />
              </GardeAdmin>
            }
          />
          <Route
            path="chantiers/referentiel"
            element={
              <GardeAdmin>
                <Chantiers />
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
          <Route
            path="chantiers/:chantierId/:fournisseurId"
            element={
              <GardeAdmin>
                <BilanBl />
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

          {/* Écrans sans remplacement construit — fix round 1 R1 (« aucune
              fonctionnalité existante n'est supprimée » l'emporte sur la
              redirection posée par erreur en Task 4) : restent MONTÉS sur
              leur ancienne URL, pas de redirection, jusqu'à ce qu'une tâche
              suivante les migre (Task 9 pour Factures). Anomalies migré par
              la Task 6 (voir ci-dessous, redirection vers `/a-regler`). */}
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

          {/* --------------------------------------------------------------
              Anciennes URL → nouvelles (spec §3, fix round 1 R1/R2) : un
              seul composant partagé pour toutes les redirections, qui
              reporte toujours les paramètres de recherche et l'ancre de
              l'URL d'origine (voir web/src/routes/). `anomalies` (Task 6) :
              `?blocId=...` (lien depuis `BilanFournisseur.tsx`, écran
              « Chantiers », pas encore migré) reste compris par `ARegler`,
              voir `pages/ARegler.tsx`. */}
          <Route path="a-traiter" element={<RedirectionAncienneUrl vers={() => "/a-regler"} />} />
          <Route path="anomalies" element={<RedirectionAncienneUrl vers={() => "/a-regler"} />} />
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
