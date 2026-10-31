/** Texte comparable : sans accents, en minuscules, espaces réduits. */
export function normaliserRecherche(texte: string): string {
  return texte
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

/** Vrai quand chaque mot de `recherche` se retrouve dans l'un des `champs`
 * (nom, client…), sans tenir compte de la casse ni des accents. Une
 * recherche vide garde tout. */
export function correspondRecherche(recherche: string, ...champs: (string | null | undefined)[]): boolean {
  const mots = normaliserRecherche(recherche).split(" ").filter((mot) => mot !== "");
  if (mots.length === 0) return true;
  const texte = champs.map((champ) => normaliserRecherche(champ ?? "")).join(" ");
  return mots.every((mot) => texte.includes(mot));
}
