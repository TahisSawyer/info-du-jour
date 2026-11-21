// Info du Jour — application (PWA) sans dépendance ni étape de compilation.
// Les données viennent des fichiers JSON publiés dans « donnees/ » par le workflow GitHub Actions.

const BORDS = [
  { id: "gauche", nom: "Gauche et centre-gauche" },
  { id: "centre", nom: "Centre et non partisans" },
  { id: "droite", nom: "Droite et centre-droit" },
];
const NOMS_BORDS_COURTS = { gauche: "gauche", centre: "centre", droite: "droite" };
const RUBRIQUES_DEFAUT = [
  ["politique", "Politique"], ["economie", "Économie & Finance"], ["technologie", "Technologie"],
  ["sciences-environnement", "Sciences & Environnement"], ["sante", "Santé"], ["culture", "Culture"],
  ["sport", "Sport"], ["societe", "Société"],
];
const ETAPES = ["Planification", "Collecte", "Regroupement et classement", "Rédaction IA", "Publication", "Mise en ligne"];

const etat = {
  config: { depot: "", workflow: "infodujour.yml", branche: "main" },
  derniere: null,   // dernière édition publiée
  edition: null,    // édition affichée (dernière ou archive)
  sources: null,
  pluralisme: null,
  index: null,
  suiviRafraichissement: null,
};

// ------------------------------------------------------------------ préférences locales
const prefs = (() => {
  let p = {};
  try { p = JSON.parse(localStorage.getItem("idj-prefs") || "{}"); } catch { p = {}; }
  return {
    get: (k, d) => (k in p ? p[k] : d),
    set: (k, v) => { p[k] = v; try { localStorage.setItem("idj-prefs", JSON.stringify(p)); } catch { /* stockage indisponible */ } },
  };
})();

// ------------------------------------------------------------------ outils
const $ = (sel, racine = document) => racine.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sansAccents = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

async function lireJSON(chemin, frais = false) {
  const r = await fetch(chemin + (frais ? `?t=${Date.now()}` : ""), { cache: frais ? "no-store" : "default" });
  if (!r.ok) throw new Error(`${chemin} : ${r.status}`);
  return r.json();
}

function dateLongue(iso) {
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}
function heure(iso) {
  return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
function ilYa(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 60) return `il y a ${min} min`;
  const h = Math.round(min / 60);
  return h < 24 ? `il y a ${h} h` : `le ${new Date(iso).toLocaleDateString("fr-FR")}`;
}

function nomRubrique(id) {
  const r = (etat.sources?.rubriques || []).find((x) => x.id === id) || RUBRIQUES_DEFAUT.find(([i]) => i === id);
  return r ? (r.nom || r[1]) : id;
}

// résumé avec renvois [S1, S2] transformés en petits liens vers les sources
function avecRenvois(texte, sujetId, cliquable = true) {
  return esc(texte).replace(/\s*\[(\s*S\d+(?:\s*[,;]\s*S\d+)*\s*)\]/g, (_, g) => {
    const cles = g.split(/[,;]/).map((c) => c.trim());
    return " " + cles.map((c) => cliquable
      ? `<a class="ref" href="#/sujet/${sujetId}/${c}" title="Voir la source ${c}">${c}</a>`
      : `<span class="ref">${c}</span>`).join("");
  });
}

function correspondMotsCles(s) {
  const mots = prefs.get("motsCles", []);
  if (!mots.length) return false;
  const texte = sansAccents(`${s.titre} ${s.resume} ${(s.mots_cles || []).join(" ")}`);
  return mots.some((m) => m && texte.includes(sansAccents(m)));
}

// ------------------------------------------------------------------ pastilles et badges
function badgeIA(s) {
  if (s.statut_ia === "ia") return `<span class="badge badge-ia" title="Résumé rédigé par l'IA${s.ia_modele ? " (" + esc(s.ia_modele) + ")" : ""} puis vérifié automatiquement">IA</span>`;
  if (s.statut_ia === "en_attente") return `<span class="badge badge-attente" title="${esc(s.motif_ia)} — un nouvel essai par l'IA est programmé. Résumé automatique en attendant.">⏳ IA en attente</span>`;
  return `<span class="badge badge-sans-ia" title="${esc(s.motif_ia || "Résumé automatique")} — résumé composé d'extraits des articles, sans IA.">⚠ Sans IA</span>`;
}

function badges(s) {
  const b = [badgeIA(s)];
  if (s.controverse || (s.points_de_vue || []).length) b.push(`<span class="badge badge-debat" title="Sujet en débat : plusieurs points de vue sont présentés">Débat</span>`);
  if (s.suivi === "nouveau") b.push(`<span class="badge badge-nouveau">Nouveau</span>`);
  if (s.suivi === "suite") b.push(`<span class="badge badge-suite" title="Sujet déjà présent ${s.precedent ? "le " + esc(s.precedent.date) : "les jours précédents"}">Suite</span>`);
  if (s.source_unique) b.push(`<span class="badge badge-unique" title="Un seul média a traité ce sujet : information non confirmée par d'autres médias">Source unique</span>`);
  else if (Object.keys(s.bords || {}).length === 1) b.push(`<span class="badge badge-partielle" title="Sujet couvert par une seule sensibilité">Couverture partielle</span>`);
  if (s.angle_mort) b.push(`<span class="badge badge-partielle" title="Sujet couvert surtout par les médias de ${s.angle_mort}">Angle mort : surtout ${s.angle_mort}</span>`);
  return `<div class="badges">${b.join("")}</div>`;
}

function barreBords(s) {
  const total = Object.values(s.bords || {}).reduce((a, b) => a + b, 0) || 1;
  const parts = BORDS.map((b) => (s.bords?.[b.id] ? `<span class="b-${b.id}" style="width:${(100 * s.bords[b.id]) / total}%"></span>` : "")).join("");
  const texte = BORDS.map((b) => `${NOMS_BORDS_COURTS[b.id]} ${s.bords?.[b.id] || 0}`).join(", ");
  return `<div class="barre-bords" role="img" aria-label="Médias par sensibilité : ${texte}" title="Médias : ${texte}">${parts}</div>`;
}

// ------------------------------------------------------------------ carte de sujet
function carte(s, rang) {
  const lus = prefs.get("lus", {});
  const dejaLu = s.suivi === "suite" && lus[s.piste] && lus[s.piste] < etat.edition.date;
  const surligne = correspondMotsCles(s);
  const reprises = s.depeches ? ` · dont ${s.depeches} reprise${s.depeches > 1 ? "s" : ""} de dépêche` : "";
  return `
  <article class="carte${surligne ? " surlignee" : ""}${dejaLu ? " repliee" : ""}" data-id="${s.id}">
    <div class="carte-tete">
      ${rang ? `<div class="rang" aria-hidden="true">${rang}</div>` : ""}
      <div style="flex:1;min-width:0">
        ${badges(s)}
        <h3><a href="#/sujet/${s.id}">${esc(s.titre)}</a></h3>
        ${dejaLu ? `<p class="evolution">Déjà lu. ${s.evolution ? "Ce qui a changé : " + esc(s.evolution) : ""} <button class="bouton bouton-discret deplier" type="button">Afficher</button></p>`
                 : (s.evolution ? `<p class="evolution"><strong>Ce qui a changé :</strong> ${esc(s.evolution)}</p>` : "")}
        <p class="resume">${avecRenvois(s.resume, s.id)}</p>
        ${barreBords(s)}
        <div class="carte-pied">
          <span>${s.nb_medias} média${s.nb_medias > 1 ? "s" : ""}${reprises}</span>
          <a href="#/sujet/${s.id}">Sources et points de vue →</a>
        </div>
      </div>
    </div>
  </article>`;
}

function listeCartes(ids, numeroter = false) {
  const sujets = ids.map((id) => etat.edition.sujets[id]).filter(Boolean);
  if (!sujets.length) return `<p class="vide">Aucun sujet pour le moment.</p>`;
  return `<div class="liste">${sujets.map((s, k) => carte(s, numeroter ? k + 1 : null)).join("")}</div>`;
}

// ------------------------------------------------------------------ bandeaux
function bandeaux() {
  const zone = $("#bandeaux");
  const e = etat.edition;
  const html = [];
  if (!e) { zone.innerHTML = ""; return; }
  if (etat.derniere && e.id !== etat.derniere.id) {
    html.push(`<div class="bandeau bandeau-info"><span class="icone">i</span><span>Vous consultez l'édition archivée du <strong>${dateLongue(e.date)}</strong>.</span><a class="bouton" href="#/">Revenir au jour</a></div>`);
  }
  if (e.statut_ia === "partiel") {
    const attente = Object.values(e.sujets).some((s) => s.statut_ia === "en_attente");
    html.push(`<div class="bandeau bandeau-partiel" role="status"><span class="icone">!</span><span><strong>Traitement IA incomplet : ${e.couverture_ia.ia} sujets sur ${e.couverture_ia.total}.</strong>
      Les sujets marqués « Sans IA » ont un résumé automatique composé d'extraits.${attente ? " Un nouvel essai par l'IA est programmé." : ""}</span></div>`);
  } else if (e.statut_ia === "aucun") {
    html.push(`<div class="bandeau bandeau-aucun" role="status"><span class="icone">!</span><span><strong>IA indisponible, édition en mode automatique.</strong>
      Résumés composés d'extraits des articles ; les points de vue sont présentés bord par bord.</span></div>`);
  }
  if (etat.nouvelle) {
    html.push(`<div class="bandeau bandeau-info"><span class="icone">↻</span><span>Une nouvelle édition est disponible.</span><button class="bouton" type="button" id="charger-nouvelle">Afficher</button></div>`);
  }
  const mots = prefs.get("motsCles", []);
  if (mots.length && e.id === etat.derniere?.id) {
    const n = Object.values(e.sujets).filter(correspondMotsCles).length;
    if (n) html.push(`<div class="bandeau bandeau-info"><span class="icone">★</span><span>${n} sujet${n > 1 ? "s correspondent" : " correspond"} à vos mots-clés suivis (surlignés).</span></div>`);
  }
  zone.innerHTML = html.join("");
  $("#charger-nouvelle")?.addEventListener("click", async () => { etat.nouvelle = false; await chargerDerniere(true); afficher(); });
}

function teteEdition() {
  const e = etat.edition;
  const ess = e.essentiel?.texte;
  return `
    <div class="tete-edition">
      <span class="date">${dateLongue(e.date)}</span>
      <span class="meta">Édition de ${heure(e.genere_le)}${e.declenchement === "manuel" ? " (rafraîchie à la demande)" : ""}${e.rattrape_le ? `, complétée à ${heure(e.rattrape_le)}` : ""} · ${e.stats.articles} articles de ${e.stats.medias_actifs} médias</span>
    </div>
    ${ess ? `<section class="essentiel" aria-label="L'essentiel">
      <h2>L'essentiel en 3 minutes ${e.essentiel.statut_ia === "ia" ? badgeIA({ statut_ia: "ia" }) : `<span class="badge badge-sans-ia" title="Titres des principaux sujets, sans synthèse IA">⚠ Sans IA</span>`}</h2>
      <p>${avecRenvois(ess, "", false)}</p>
      ${e.audio ? `<audio controls preload="none" src="donnees/${esc(e.audio)}"></audio>` : ""}
    </section>` : ""}`;
}

// ------------------------------------------------------------------ pages
function pageAccueil(perimetre) {
  const e = etat.edition;
  return `${teteEdition()}
    <h1>${perimetre === "france" ? "Top 10 France" : "Top 10 International"}</h1>
    ${listeCartes(e.tops[perimetre] || [], true)}`;
}

function ordreRubriques() {
  const connues = (etat.edition?.rubriques || []).map((r) => r.id);
  const ordre = prefs.get("ordreRubriques", connues).filter((id) => connues.includes(id));
  connues.forEach((id) => { if (!ordre.includes(id)) ordre.push(id); });
  const masquees = new Set(prefs.get("rubriquesMasquees", []));
  return ordre.filter((id) => !masquees.has(id));
}

function pageRubriques() {
  const e = etat.edition;
  const par = Object.fromEntries(e.rubriques.map((r) => [r.id, r]));
  const blocs = ordreRubriques().map((id) => par[id]).filter((r) => r && r.sujets.length).map((r) => `
    <section class="rubrique" id="rub-${r.id}">
      <div class="rubrique-tete"><h2>${esc(r.nom)}</h2></div>
      ${listeCartes(r.sujets)}
    </section>`).join("");
  return `${teteEdition()}<p class="intro">Les sujets déjà présents dans les Tops 10 ne sont pas répétés ici. Ordre et affichage des rubriques : <a href="#/reglages">Réglages</a>.</p>${blocs || `<p class="vide">Aucune rubrique à afficher.</p>`}`;
}

function pageAnglesMorts() {
  const e = etat.edition;
  return `<h1>Angles morts</h1>
    <p class="intro">Sujets couverts massivement par les médias d'un seul bord et peu ou pas par l'autre. Les comparer aide à
    repérer ce que chaque famille de presse met en avant… ou laisse de côté.</p>
    ${listeCartes(e.angles_morts || [])}`;
}

function pageSujet(id, cle) {
  const e = etat.edition;
  const s = e.sujets[id];
  if (!s) return `<p class="vide">Ce sujet n'existe pas dans l'édition affichée. <a href="#/">Retour</a></p>`;
  const lus = prefs.get("lus", {});
  lus[s.piste || s.id] = e.date;
  const cles = Object.keys(lus);
  if (cles.length > 400) cles.slice(0, cles.length - 400).forEach((k) => delete lus[k]);
  prefs.set("lus", lus);
  const parCle = Object.fromEntries(s.sources.map((x) => [x.cle, x]));
  const refs = (liste) => (liste || []).map((c) => parCle[c] ? `<a class="ref" href="#/sujet/${s.id}/${c}">${c} ${esc(parCle[c].media)}</a>` : "").join(" ");
  let pdv = "";
  if ((s.points_de_vue || []).length) {
    pdv = `<section class="bloc"><h2>Points de vue en présence</h2><div class="colonnes">${s.points_de_vue.map((p) => `
      <div class="pdv"><strong>${esc(p.position)}</strong>${esc(p.synthese)}<div>${refs(p.sources)}</div></div>`).join("")}</div></section>`;
  } else if (s.par_bord) {
    pdv = `<section class="bloc"><h2>Comment chaque bord en parle</h2><div class="colonnes">${BORDS.map((b) => `
      <div class="colonne c-${b.id}"><h3>${b.nom}</h3>${(s.par_bord[b.id] || []).map((x) => `
        <p class="extrait"><span class="media">${esc(x.media)}${x.opinion ? " · tribune" : ""}</span>
        <a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.titre)}</a>${x.chapo ? `<br>${esc(x.chapo)}` : ""}</p>`).join("") || `<p class="vide">Aucun média de ce bord.</p>`}</div>`).join("")}</div></section>`;
  }
  const sourcesHtml = s.sources.map((x) => `
    <li id="src-${x.cle}">
      <span class="cle">${x.cle}</span><strong>${esc(x.media)}</strong>
      <span class="etiquettes"><span class="etiq"><span class="puce b-${x.bord}"></span>${esc(x.orientation_libelle)}</span>
        ${x.opinion ? `<span class="etiq">Tribune / opinion</span>` : ""}${x.reprise ? `<span class="etiq">Reprise de dépêche</span>` : ""}
        ${x.payant ? `<span class="etiq etiq-payant" title="Article souvent réservé aux abonnés">Abonnés</span>` : ""}${x.langue !== "fr" ? `<span class="etiq">${esc(x.langue.toUpperCase())}</span>` : ""}</span>
      <div><a class="titre-source" href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.titre)}</a></div>
      ${x.chapo ? `<div>${esc(x.chapo)}</div>` : ""}
      <small>${ilYa(x.publie_le)}</small>
    </li>`).join("");
  const infoIA = s.statut_ia === "ia"
    ? `Résumé rédigé par l'IA (${esc(s.ia_modele || "")}) à partir des extraits ci-dessous, puis vérifié automatiquement : sources citées, neutralité du vocabulaire, équilibre des points de vue.`
    : `Résumé automatique composé d'extraits des articles, sans IA. Motif : ${esc(s.motif_ia || "—")}.${s.statut_ia === "en_attente" ? " Un nouvel essai par l'IA est programmé." : ""}`;
  const depot = etat.config.depot;
  const signaler = depot ? `https://github.com/${depot}/issues/new?labels=biais&title=${encodeURIComponent("Biais signalé : " + s.titre)}&body=${encodeURIComponent(`Édition : ${e.id}\nSujet : ${s.titre}\n\nRésumé :\n${s.resume}\n\nCe qui me semble biaisé :\n`)}` : "";
  setTimeout(() => { if (cle) document.getElementById("src-" + cle)?.scrollIntoView({ behavior: "smooth", block: "center" }); }, 50);
  return `<article class="detail">
    <a class="retour" href="javascript:history.back()">← Retour</a>
    ${badges(s)}
    <h1>${esc(s.titre)}</h1>
    <p class="intro">${s.perimetre === "france" ? "France" : "International"} · ${esc(nomRubrique(s.rubrique))} · ${s.nb_medias} média${s.nb_medias > 1 ? "s" : ""} · dernier article ${ilYa(s.dernier)}</p>
    ${s.evolution ? `<p class="evolution"><strong>Ce qui a changé${s.precedent ? " depuis le " + esc(s.precedent.date) : ""} :</strong> ${esc(s.evolution)}</p>` : ""}
    <p class="resume">${avecRenvois(s.resume, s.id)}</p>
    ${s.limites ? `<p class="limites">${esc(s.limites)}</p>` : ""}
    ${s.source_unique ? `<p class="limites">Un seul média a traité ce sujet : information non confirmée par d'autres médias.</p>` : ""}
    ${barreBords(s)}
    ${pdv}
    <section class="bloc"><h2>Sources (${s.sources.length} sur ${s.nb_medias} médias)</h2><ul class="sources-liste">${sourcesHtml}</ul></section>
    <p class="intro" style="font-size:.88rem">${infoIA}</p>
    <div class="actions-detail">
      ${signaler ? `<a class="bouton" href="${signaler}" target="_blank" rel="noopener">Signaler un biais</a>` : ""}
      ${navigator.share ? `<button class="bouton" type="button" id="partager">Partager</button>` : ""}
    </div>
  </article>`;
}

function graphiquePluralisme(series) {
  if (!series?.length) return `<p class="vide">L'historique se construit au fil des éditions.</p>`;
  const L = 640, H = 170, g = 46, bas = 22, largeur = Math.min((L - g) / series.length, 36);
  const barres = series.map((p, i) => {
    const total = BORDS.reduce((a, b) => a + (p.bords[b.id] || 0), 0) || 1;
    let y = 8;
    const h = H - bas - 8;
    return BORDS.map((b) => {
      const hh = (h * (p.bords[b.id] || 0)) / total;
      const r = `<rect x="${g + i * largeur + 1}" y="${y}" width="${Math.max(largeur - 2, 1)}" height="${hh}" class="b-${b.id}" fill="var(--bord-${b.id})"><title>${p.date} — ${NOMS_BORDS_COURTS[b.id]} : ${Math.round((100 * (p.bords[b.id] || 0)) / total)} %</title></rect>`;
      y += hh;
      return r;
    }).join("");
  }).join("");
  const axe = [0, 50, 100].map((v) => `<text x="${g - 6}" y="${8 + (H - bas - 8) * (1 - v / 100) + 4}" text-anchor="end">${v} %</text>`).join("");
  const dates = [0, series.length - 1].filter((v, i, a) => a.indexOf(v) === i).map((i) => `<text x="${g + i * largeur + largeur / 2}" y="${H - 6}" text-anchor="middle">${series[i].date.slice(5)}</text>`).join("");
  return `<div class="graphique"><svg viewBox="0 0 ${L} ${H}" role="img" aria-label="Part des liens affichés par sensibilité, par édition">${axe}${barres}${dates}</svg></div>
    <p class="legende-bords" style="font-size:.85rem">${BORDS.map((b) => `<span><span class="puce b-${b.id}"></span>${b.nom}</span>`).join("")}</p>`;
}

function pageSources() {
  const src = etat.sources;
  if (!src) return `<p class="vide">Informations sur les sources indisponibles.</p>`;
  const rep = src.repartition_articles || {};
  const max = Math.max(1, ...Object.values(rep));
  const total = Object.values(rep).reduce((a, b) => a + b, 0);
  const ordreOrient = src.orientations.map((o) => o.id);
  const catalogue = [...src.catalogue].sort((a, b) => ordreOrient.indexOf(a.orientation) - ordreOrient.indexOf(b.orientation) || a.nom.localeCompare(b.nom));
  const dernier = etat.pluralisme?.[etat.pluralisme.length - 1];
  return `<h1>Nos sources</h1>
    <p class="intro">Info du Jour lit chaque heure les flux de ${src.catalogue.filter((c) => c.actif).length} médias aux lignes éditoriales variées.
    Chaque média compte pour une voix, quel que soit son nombre d'articles. Les orientations sont indicatives et modifiables.</p>
    <section class="bloc"><h2>Articles collectés sur 30 heures (${total})</h2><div class="repartition">${src.orientations.map((o) => `
      <div class="ligne"><span>${esc(o.libelle)}</span><span class="jauge"><span style="width:${(100 * (rep[o.id] || 0)) / max}%"></span></span><span>${rep[o.id] || 0}</span></div>`).join("")}</div></section>
    <section class="bloc"><h2>Équilibre des liens affichés sur 30 éditions</h2>${graphiquePluralisme(etat.pluralisme)}
      ${dernier?.alertes?.length ? `<p class="limites">Alerte d'équilibre : ${dernier.alertes.map(esc).join(" ; ")}</p>` : `<p class="intro" style="font-size:.88rem">Aucune alerte d'équilibre sur la dernière édition.</p>`}
      ${dernier ? `<p class="intro" style="font-size:.88rem">Dernière édition : diversité moyenne ${Math.round(dernier.diversite_moyenne * 100)} %, sujets à couverture partielle ${Math.round(dernier.part_couverture_partielle * 100)} %, sujets avec points de vue ${Math.round(dernier.part_points_de_vue * 100)} %.</p>` : ""}
    </section>
    <section class="bloc"><h2>Catalogue</h2><div style="overflow-x:auto"><table>
      <thead><tr><th>Média</th><th>Orientation</th><th>Pays</th><th>État du flux</th></tr></thead>
      <tbody>${catalogue.map((c) => `<tr><td>${esc(c.nom)}${c.payant ? ` <span class="etiq etiq-payant">Abonnés</span>` : ""}</td><td>${esc(c.orientation_libelle)}</td><td>${esc(c.pays)}</td>
        <td>${!c.actif ? "désactivé" : c.alerte ? `<span class="etat-ko" title="${esc(c.erreur || "")}">✗ en échec (${c.echecs} fois)</span>` : c.dernier_succes ? `<span class="etat-ok">✓</span> ${ilYa(c.dernier_succes)}` : (c.erreur ? `<span class="etat-ko">✗ ${esc(c.erreur)}</span>` : "—")}</td></tr>`).join("")}</tbody>
    </table></div>
    ${etat.config.depot ? `<p class="aide">Modifier le catalogue : <a href="https://github.com/${etat.config.depot}/edit/${etat.config.branche}/config/sources.yaml" target="_blank" rel="noopener">éditer sources.yaml sur GitHub</a> (pris en compte à l'exécution suivante).</p>` : ""}
    </section>`;
}

function pageArchives() {
  const idx = etat.index || [];
  return `<h1>Archives</h1><p class="intro">Les éditions sont conservées un an.</p>
    <div class="archives">${idx.map((e) => `<a href="#/edition/${e.date}"><span>${dateLongue(e.date)}</span>
      <span class="intro">${e.statut_ia === "complet" ? "IA complète" : e.statut_ia === "partiel" ? `IA ${e.couverture_ia.ia}/${e.couverture_ia.total}` : "sans IA"}</span></a>`).join("") || `<p class="vide">Aucune archive.</p>`}</div>`;
}

function pageReglages() {
  const rub = etat.edition?.rubriques?.map((r) => [r.id, r.nom]) || RUBRIQUES_DEFAUT;
  const noms = Object.fromEntries(rub);
  const ordre = prefs.get("ordreRubriques", rub.map((r) => r[0])).filter((id) => noms[id]);
  rub.forEach(([id]) => { if (!ordre.includes(id)) ordre.push(id); });
  const masquees = new Set(prefs.get("rubriquesMasquees", []));
  const theme = prefs.get("theme", "auto");
  return `<div class="reglages"><h1>Réglages</h1>
    <p class="intro">Ces réglages sont enregistrés sur cet appareil uniquement.</p>
    <fieldset><legend>Rubriques</legend><ul class="ordre-rubriques">${ordre.map((id, k) => `
      <li data-id="${id}"><input type="checkbox" ${masquees.has(id) ? "" : "checked"} aria-label="Afficher ${esc(noms[id])}"><span class="nom">${esc(noms[id])}</span>
      <button type="button" data-sens="-1" ${k === 0 ? "disabled" : ""} aria-label="Monter">↑</button><button type="button" data-sens="1" ${k === ordre.length - 1 ? "disabled" : ""} aria-label="Descendre">↓</button></li>`).join("")}</ul></fieldset>
    <fieldset><legend>Mots-clés suivis</legend>
      <label for="mots">Mots-clés séparés par des virgules</label>
      <input id="mots" type="text" value="${esc(prefs.get("motsCles", []).join(", "))}" placeholder="ex. retraites, Ukraine, intelligence artificielle">
      <p class="aide">Les sujets correspondants sont surlignés. Le classement reste le même pour tous : il ne s'adapte jamais à vos lectures.</p>
      <label><input id="notif" type="checkbox" ${prefs.get("notifications", false) ? "checked" : ""}> Me prévenir quand une nouvelle édition contient un mot-clé (si l'application est ouverte ou installée)</label>
    </fieldset>
    <fieldset><legend>Affichage</legend>
      <label><input type="radio" name="theme" value="auto" ${theme === "auto" ? "checked" : ""}> Thème automatique</label>
      <label><input type="radio" name="theme" value="clair" ${theme === "clair" ? "checked" : ""}> Clair</label>
      <label><input type="radio" name="theme" value="sombre" ${theme === "sombre" ? "checked" : ""}> Sombre</label>
      <button class="bouton" type="button" id="oublier-lus" style="margin-top:8px">Effacer l'historique de lecture</button>
    </fieldset>
    <fieldset><legend>Rafraîchissement à la demande</legend>
      <p class="aide">Le bouton « Rafraîchir » demande à GitHub de lancer une nouvelle édition. Il faut pour cela un jeton d'accès personnel
      (« fine-grained token ») limité à ce dépôt, avec la permission <strong>Actions : lecture et écriture</strong>. Le jeton reste sur cet appareil.</p>
      <label for="depot">Dépôt GitHub (propriétaire/nom)</label>
      <input id="depot" type="text" value="${esc(prefs.get("depot", etat.config.depot))}" placeholder="votre-compte/info-du-jour">
      <label for="jeton">Jeton d'accès GitHub</label>
      <input id="jeton" type="password" value="${esc(prefs.get("jeton", ""))}" autocomplete="off" placeholder="github_pat_…">
      <div class="actions-detail">
        <button class="bouton" type="button" id="enregistrer-jeton">Enregistrer et tester</button>
        <button class="bouton" type="button" id="completer-ia">Compléter les résumés IA maintenant</button>
        ${etat.config.depot ? `<a class="bouton" href="https://github.com/${etat.config.depot}/actions" target="_blank" rel="noopener">Historique des exécutions</a>` : ""}
      </div>
      <p class="aide" id="resultat-jeton"></p>
    </fieldset></div>`;
}

function brancherReglages() {
  const liste = $(".ordre-rubriques");
  const lireOrdre = () => [...liste.querySelectorAll("li")].map((li) => li.dataset.id);
  liste?.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (!b) return;
    const ordre = lireOrdre();
    const i = ordre.indexOf(b.closest("li").dataset.id);
    const j = i + Number(b.dataset.sens);
    [ordre[i], ordre[j]] = [ordre[j], ordre[i]];
    prefs.set("ordreRubriques", ordre);
    afficher();
  });
  liste?.addEventListener("change", () => {
    prefs.set("rubriquesMasquees", [...liste.querySelectorAll("li")].filter((li) => !li.querySelector("input").checked).map((li) => li.dataset.id));
  });
  $("#mots")?.addEventListener("change", (ev) => prefs.set("motsCles", ev.target.value.split(",").map((m) => m.trim()).filter(Boolean)));
  $("#notif")?.addEventListener("change", async (ev) => {
    if (ev.target.checked && "Notification" in window) {
      const r = await Notification.requestPermission();
      ev.target.checked = r === "granted";
    }
    prefs.set("notifications", ev.target.checked);
  });
  document.querySelectorAll('input[name="theme"]').forEach((r) => r.addEventListener("change", () => { prefs.set("theme", r.value); appliquerTheme(); }));
  $("#oublier-lus")?.addEventListener("click", () => { prefs.set("lus", {}); $("#oublier-lus").textContent = "Historique effacé"; });
  $("#enregistrer-jeton")?.addEventListener("click", async () => {
    prefs.set("depot", $("#depot").value.trim());
    prefs.set("jeton", $("#jeton").value.trim());
    const sortie = $("#resultat-jeton");
    sortie.textContent = "Test en cours…";
    try {
      const r = await github(`/repos/${depot()}/actions/workflows/${etat.config.workflow}`);
      sortie.textContent = `✓ Accès vérifié : workflow « ${r.name} » trouvé.`;
    } catch (e) { sortie.textContent = "✗ " + e.message; }
  });
  $("#completer-ia")?.addEventListener("click", () => lancer("rattrapage"));
}

// ------------------------------------------------------------------ GitHub : rafraîchissement à la demande
const depot = () => prefs.get("depot", "") || etat.config.depot;

async function github(chemin, options = {}) {
  const jeton = prefs.get("jeton", "");
  if (!jeton) throw new Error("Aucun jeton GitHub enregistré (Réglages).");
  const r = await fetch("https://api.github.com" + chemin, {
    ...options,
    headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${jeton}`, "X-GitHub-Api-Version": "2022-11-28", ...(options.headers || {}) },
  });
  if (r.status === 204) return {};
  const corps = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = { 401: "jeton refusé ou expiré", 403: "jeton sans la permission Actions (écriture)", 404: "dépôt ou workflow introuvable (vérifiez le nom du dépôt et les droits du jeton)" }[r.status];
    throw new Error(msg || corps.message || `erreur ${r.status}`);
  }
  return corps;
}

function dialogue(html) {
  const d = $("#dialogue");
  d.innerHTML = html;
  if (!d.open) d.showModal();
  return d;
}

async function demanderRafraichissement() {
  if (!prefs.get("jeton", "") || !depot()) {
    const d = dialogue(`<h2>Rafraîchir l'édition</h2><p>Pour lancer une édition depuis l'application, enregistrez d'abord un jeton GitHub dans les réglages.
      Les éditions automatiques continuent sans cela (chaque jour vers 17 h 50).</p>
      <div class="boutons-dialogue"><button class="bouton" value="annuler">Fermer</button><a class="bouton bouton-plein" href="#/reglages">Aller aux réglages</a></div>`);
    d.querySelector("button").onclick = () => d.close();
    d.querySelector("a").onclick = () => d.close();
    return;
  }
  const e = etat.derniere;
  const recente = e && Date.now() - new Date(e.genere_le) < 30 * 60000;
  const d = dialogue(`<h2>Lancer une nouvelle édition ?</h2>
    <p>La collecte, le regroupement et la rédaction prennent environ 5 à 15 minutes. L'édition actuelle reste lisible pendant ce temps.</p>
    ${recente ? `<p class="limites">La dernière édition date de ${ilYa(e.genere_le)}. Un délai de 30 minutes est prévu entre deux rafraîchissements pour ménager le quota d'IA.</p>
      <label><input type="checkbox" id="forcer"> Lancer quand même</label>` : ""}
    <div class="boutons-dialogue"><button class="bouton" id="annuler">Annuler</button><button class="bouton bouton-plein" id="confirmer">Lancer</button></div>`);
  $("#annuler", d).onclick = () => d.close();
  $("#confirmer", d).onclick = () => lancer("edition", $("#forcer", d)?.checked);
}

async function lancer(mode, forcer = false) {
  const debut = new Date(Date.now() - 15000);
  const d = dialogue(`<h2>${mode === "edition" ? "Nouvelle édition en cours" : "Complément des résumés IA"}</h2><p id="etat-run">Envoi de la demande à GitHub…</p>
    <ul class="etapes" id="etapes"></ul><div class="boutons-dialogue"><button class="bouton" id="fermer">Continuer en arrière-plan</button></div>`);
  $("#fermer", d).onclick = () => d.close();
  $("#btn-rafraichir").disabled = true;
  try {
    await github(`/repos/${depot()}/actions/workflows/${etat.config.workflow}/dispatches`, {
      method: "POST", body: JSON.stringify({ ref: etat.config.branche || "main", inputs: { mode, forcer: forcer ? "true" : "false" } }),
    });
  } catch (e) {
    $("#etat-run", d).textContent = "Impossible de lancer : " + e.message;
    $("#btn-rafraichir").disabled = false;
    return;
  }
  suivreExecution(debut, mode);
}

async function suivreExecution(debut, mode) {
  const ancienne = etat.derniere?.id;
  let run = null;
  for (let k = 0; k < 400; k++) {
    await new Promise((r) => setTimeout(r, run ? 5000 : 3000));
    try {
      if (!run) {
        const runs = await github(`/repos/${depot()}/actions/workflows/${etat.config.workflow}/runs?event=workflow_dispatch&per_page=5`);
        run = (runs.workflow_runs || []).find((r) => new Date(r.created_at) >= debut) || null;
        if (!run) { majDialogue("En attente du démarrage par GitHub…"); continue; }
      }
      const [r, jobs] = await Promise.all([github(`/repos/${depot()}/actions/runs/${run.id}`), github(`/repos/${depot()}/actions/runs/${run.id}/jobs`)]);
      const etapes = {};
      for (const job of jobs.jobs || []) {
        for (const st of job.steps || []) etapes[st.name] = st;
        if (job.name === "Mise en ligne") etapes["Mise en ligne"] = { status: job.status, conclusion: job.conclusion };
      }
      afficherEtapes(etapes, mode);
      if (r.status === "completed") {
        if (r.conclusion !== "success") { majDialogue(`L'exécution s'est terminée en erreur. Détails : ${r.html_url}`); break; }
        const publie = etapes["Mise en ligne"] && etapes["Mise en ligne"].conclusion === "success";
        if (!publie) {
          majDialogue(mode === "edition" ? "Aucune nouvelle édition : la dernière est trop récente (délai de 30 minutes) ou rien n'a changé." : "Aucun résumé à compléter pour le moment.");
          break;
        }
        majDialogue("Terminé. Mise à jour de l'affichage…");
        for (let j = 0; j < 40; j++) {
          const e = await lireJSON("donnees/edition.json", true).catch(() => null);
          if (e && (e.id !== ancienne || e.rattrape_le !== etat.derniere?.rattrape_le)) {
            etat.derniere = e; etat.edition = e; etat.nouvelle = false;
            majDialogue("Nouvelle édition affichée.");
            afficher();
            break;
          }
          await new Promise((res) => setTimeout(res, 6000));
        }
        break;
      }
    } catch (e) { majDialogue("Suivi interrompu : " + e.message); break; }
  }
  $("#btn-rafraichir").disabled = false;
}

function majDialogue(texte) {
  const p = document.getElementById("etat-run");
  if (p) p.textContent = texte;
}

function afficherEtapes(etapes, mode) {
  const ul = document.getElementById("etapes");
  if (!ul) return;
  const liste = mode === "edition" ? ETAPES : ["Planification", "Rattrapage IA", "Mise en ligne"];
  ul.innerHTML = liste.map((nom) => {
    const st = etapes[nom];
    let cls = "e-attente", sym = "○";
    if (st?.status === "completed") { cls = st.conclusion === "skipped" ? "e-ignore" : "e-fait"; sym = st.conclusion === "skipped" ? "–" : st.conclusion === "success" ? "✓" : "✗"; }
    else if (st?.status === "in_progress") { cls = "e-cours"; sym = "●"; }
    return `<li class="${cls}"><span>${sym}</span>${nom}</li>`;
  }).join("");
  majDialogue("Traitement en cours sur les serveurs de GitHub…");
}

// ------------------------------------------------------------------ navigation
function appliquerTheme() {
  const t = prefs.get("theme", "auto");
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}

async function afficher() {
  const h = location.hash.replace(/^#\/?/, "");
  const [route, a1, a2] = h.split("/");
  const main = $("#contenu");
  if (route === "edition" && a1) {
    try {
      etat.edition = a1 === etat.derniere?.date ? etat.derniere : await lireJSON(`donnees/editions/${a1}.json`);
    } catch { main.innerHTML = `<p class="vide">Édition du ${esc(a1)} introuvable. <a href="#/archives">Archives</a></p>`; return; }
  } else if (!["sujet", "edition"].includes(route) && etat.derniere && etat.edition !== etat.derniere && route !== "archives") {
    if (route === "" || route === "international") etat.edition = etat.derniere;
  }
  if (!etat.edition) { main.innerHTML = `<p class="vide">Aucune édition publiée pour l'instant. La première édition sera disponible après la première exécution programmée.</p>`; return; }
  const onglet = { "": "france", international: "international", rubriques: "rubriques", "angles-morts": "angles-morts", sources: "sources", archives: "archives", edition: "france" }[route];
  document.querySelectorAll(".onglets a").forEach((a) => a.classList.toggle("actif", a.dataset.onglet === onglet));
  if (route === "sources" && !etat.pluralisme) {
    [etat.pluralisme, etat.sources] = await Promise.all([lireJSON("donnees/pluralisme.json").catch(() => []), etat.sources || lireJSON("donnees/sources.json").catch(() => null)]);
  }
  if (route === "archives" && !etat.index) etat.index = await lireJSON("donnees/index.json", true).catch(() => []);
  const pages = {
    "": () => pageAccueil("france"), edition: () => pageAccueil("france"), international: () => pageAccueil("international"),
    rubriques: pageRubriques, "angles-morts": pageAnglesMorts, sujet: () => pageSujet(a1, a2), sources: pageSources,
    archives: pageArchives, reglages: pageReglages,
  };
  main.innerHTML = (pages[route] || pages[""])();
  bandeaux();
  if (route === "reglages") brancherReglages();
  if (route === "sujet") {
    $("#partager")?.addEventListener("click", () => navigator.share({ title: etat.edition.sujets[a1]?.titre, url: location.href }).catch(() => {}));
    if (!a2) window.scrollTo(0, 0);
  } else window.scrollTo(0, 0);
  main.querySelectorAll(".deplier").forEach((b) => b.addEventListener("click", () => b.closest(".carte").classList.remove("repliee")));
}

async function chargerDerniere(frais = false) {
  etat.derniere = await lireJSON("donnees/edition.json", frais);
  etat.edition = etat.derniere;
}

async function verifierNouvelle() {
  try {
    const e = await lireJSON("donnees/edition.json", true);
    if (etat.derniere && e.id !== etat.derniere.id) {
      etat.nouvelle = true;
      if (prefs.get("notifications", false) && "Notification" in window && Notification.permission === "granted") {
        const n = Object.values(e.sujets).filter(correspondMotsCles);
        if (n.length) new Notification("Info du Jour", { body: `${n.length} sujet(s) sur vos mots-clés : ${n[0].titre}`, icon: "icones/icone-192.png" });
      }
      bandeaux();
    } else if (etat.derniere && e.rattrape_le !== etat.derniere.rattrape_le) {
      etat.derniere = e;
      if (etat.edition?.id === e.id) { etat.edition = e; afficher(); }
    }
  } catch { /* hors ligne */ }
}

async function demarrer() {
  appliquerTheme();
  try { etat.config = { ...etat.config, ...(await lireJSON("config.json", true)) }; } catch { /* configuration locale */ }
  try { await chargerDerniere(true); } catch { /* aucune édition encore */ }
  lireJSON("donnees/sources.json").then((s) => { etat.sources = s; }).catch(() => {});
  window.addEventListener("hashchange", afficher);
  $("#btn-rafraichir").addEventListener("click", demanderRafraichissement);
  await afficher();
  setInterval(verifierNouvelle, 10 * 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) verifierNouvelle(); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

demarrer();
