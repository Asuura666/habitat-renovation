import type { ReactElement } from "react";
import { Route, Routes } from "react-router";

import { EcouteAuthentification } from "./components/EcouteAuthentification";
import { Gabarit } from "./components/Gabarit";
import { ARegler } from "./pages/ARegler";
import { ChantiersListe } from "./pages/ChantiersListe";
import { Connexion } from "./pages/Connexion";
import { DocumentsListe } from "./pages/DocumentsListe";
import { FicheChantier } from "./pages/FicheChantier";
import { FicheFournisseur } from "./pages/FicheFournisseur";
import { FournisseursListe } from "./pages/FournisseursListe";
import { Journal } from "./pages/Journal";
import { PageBl } from "./pages/PageBl";
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
          {/* Vue d'ensemble (admin) — Task 5, maquette `Main`, écran monté
              par `RedirectionAccueil.tsx` (remplace `EcranEnConstruction`
              posé par la Task 4, supprimé). `GardeAdmin` y renvoie déjà
              l'agent vers `/documents`. */}
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

          {/* Fournisseurs (remplace « Bilan par fournisseur ») — Task 9.
              `BilanFournisseursGlobal`/`BilanChantiersFournisseur`
              (`pages/BilanFournisseur.tsx`) ne sont plus montés ici ;
              `BilanFournisseursChantier`/`BilanBl`, dans le même fichier,
              restent utilisés par les routes `chantiers/...` ci-dessus
              (Task 7, non touchées) — le fichier n'est donc pas supprimé. */}
          <Route
            path="fournisseurs"
            element={
              <GardeAdmin>
                <FournisseursListe />
              </GardeAdmin>
            }
          />
          <Route
            path="fournisseurs/:fournisseurId"
            element={
              <GardeAdmin>
                <FicheFournisseur />
              </GardeAdmin>
            }
          />

          {/* Documents (remplace « Factures »/« BL déposés », Task 8) —
              admin (tous) et agent (ses dépôts, lecture seule) : aucune
              `GardeAdmin` ici, comme avant Task 4, `DocumentsListe` gère
              elle-même la vue agent restreinte. `documents/:id` et `bl/:id`
              montent le même écran `PageBl`, qui tente d'abord un document
              (BL/enlèvement) puis, sur 404, délègue à `FactureDetail` — un
              même identifiant peut être celui d'un document ou d'une
              facture (voir `pages/PageBl.tsx`). */}
          <Route path="documents" element={<DocumentsListe />} />
          <Route path="documents/:id" element={<PageBl />} />
          <Route path="bl/:id" element={<PageBl />} />

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
          <Route path="factures" element={<RedirectionAncienneUrl vers={() => "/documents"} />} />
          <Route
            path="factures/:id"
            element={<RedirectionAncienneUrl vers={(p) => `/documents/${p.id ?? ""}`} />}
          />

          <Route path="*" element={<RedirectionAncienneUrl vers={() => "/"} />} />
        </Route>
      </Routes>
    </>
  );
}
