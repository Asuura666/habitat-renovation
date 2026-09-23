/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Charte « Registre » (direction A retenue, plan de la refonte du
      // front §2/§8) : fond ivoire, surfaces blanches, accent vert
      // profond, trois couleurs d'état toujours doublées d'un libellé
      // (jamais la couleur seule — spec §2). Valeurs reprises telles
      // quelles des maquettes (Main/ARegler/FicheChantier.dc.html).
      colors: {
        fond: "#f6f4ef",
        surface: "#ffffff",
        bordure: "#e3dfd5",
        encre: "#1c1b18",
        "encre-2": "#5f5b52",
        accent: "#1f4d3a",
        "accent-fonce": "#123126",
        conforme: "#2f7a55",
        ecart: "#c77700",
        "ecart-texte": "#a86400",
        alerte: "#b3261e",
      },
      fontFamily: {
        // Fraunces (titres et grands chiffres), IBM Plex Sans (texte),
        // IBM Plex Mono (montants, numéros) — auto-hébergées via
        // `@fontsource/*` (voir `main.tsx`), jamais Google Fonts (CSP
        // `default-src 'self'`, spec §2).
        titre: ["Fraunces", "Georgia", "serif"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["IBM Plex Mono", "monospace"],
      },
      borderRadius: {
        carte: "14px",
      },
    },
  },
  plugins: [],
};
