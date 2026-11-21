# Info du Jour

Application d'actualités (PWA) pluraliste et gratuite.

Chaque jour vers 17 h 50, elle publie :
- un **Top 10 France** et un **Top 10 International** ;
- des **rubriques** de 5 sujets (Politique, Économie & Finance, Technologie, Sciences & Environnement, Santé, Culture, Sport, Société) ;
- des **angles morts** : les sujets couverts surtout par un seul bord ;
- **L'essentiel en 3 minutes**, en tête d'édition.

Chaque sujet comporte un résumé neutre, les points de vue en présence et les liens vers les articles d'origine. Ces articles viennent de 48 médias d'orientations variées.

Tout fonctionne sur les services gratuits de **GitHub**, sans serveur ni NAS :

| Rôle | Service |
| --- | --- |
| Traitements (collecte, regroupement, IA) | GitHub Actions |
| Stockage des données | Branche `etat` du dépôt |
| Site et application | GitHub Pages |
| Rédaction des résumés | Gemini (offre gratuite) ; Mistral en option, payant à l'usage |

---

## Installation (environ 30 minutes, une seule fois)

### 1. Créer le dépôt
1. Créez un compte gratuit sur [github.com](https://github.com) si vous n'en avez pas.
2. En haut à droite, cliquez **+ › New repository**.
   - Nom : `info-du-jour`.
   - Visibilité : **Public**. C'est indispensable pour bénéficier de GitHub Actions et GitHub Pages gratuits et illimités. Vos clés restent secrètes, voir l'étape 3.
   - Cliquez **Create repository**.
3. Sur la page du dépôt vide, cliquez **uploading an existing file**. Glissez-y **tout le contenu** du dossier `info-du-jour`, puis cliquez **Commit changes**.
   > ⚠️ Le dossier `.github` est un dossier masqué sur Mac et Windows : vérifiez qu'il est bien envoyé. Sinon, créez à la main le fichier `.github/workflows/infodujour.yml` avec **Add file › Create new file** et collez-y son contenu. Faites de même pour les deux autres fichiers de ce dossier. Vous pouvez aussi utiliser l'application GitHub Desktop.

### 2. Obtenir les clés d'IA (gratuites)
- **Gemini (principal, gratuit)** : [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). Cliquez **Create API key**.
- **Mistral (facultatif, payant à l'usage)** : depuis fin 2026, Mistral ne propose plus d'offre gratuite pour l'API ; il faut la formule *Pay-as-you-go* sur [console.mistral.ai](https://console.mistral.ai) (quelques centimes par jour pour cette application).
- Facultatif, pour élargir la couverture : [GNews](https://gnews.io), [NewsData.io](https://newsdata.io) et [The Guardian Open Platform](https://open-platform.theguardian.com/access/).

Sans aucune clé, l'application fonctionne quand même en mode sans IA : résumés par extraits et colonnes par bord, avec la pastille « Sans IA ».

### 3. Enregistrer les clés dans GitHub (secrets)
Dans le dépôt, allez dans **Settings › Secrets and variables › Actions › New repository secret**, puis créez :

| Nom du secret | Valeur |
| --- | --- |
| `MISTRAL_API_KEY` | votre clé Mistral |
| `GEMINI_API_KEY` | votre clé Gemini |
| `GNEWS_API_KEY`, `NEWSDATA_API_KEY`, `GUARDIAN_API_KEY` | facultatifs |

Les secrets ne sont jamais visibles, même dans un dépôt public.

### 4. Activer le site
1. Allez dans **Settings › Pages › Build and deployment › Source** et choisissez **GitHub Actions**.
2. Allez dans **Settings › Actions › General › Workflow permissions**, cochez **Read and write permissions**, puis cliquez **Save**.

### 5. Lancer la première édition
1. Ouvrez l'onglet **Actions**. Si GitHub le demande, acceptez d'activer les workflows.
2. Cliquez **Info du Jour › Run workflow**, laissez le mode `edition`, puis cliquez **Run workflow**.
3. L'exécution dure environ 5 à 15 minutes. La toute première est un peu plus longue, car le modèle de regroupement se télécharge.
4. Votre application est ensuite en ligne à l'adresse **https://VOTRE-COMPTE.github.io/info-du-jour/**. L'adresse est rappelée dans **Settings › Pages**.

Lancez aussi une fois **Actions › Vérifier les flux › Run workflow**. Le rapport indique les flux RSS qui répondent mal : certains médias changent l'adresse de leur flux. Corrigez ou désactivez-les dans `config/sources.yaml`.

### 6. Installer l'application sur le téléphone
Ouvrez l'adresse dans Chrome (Android) ou Safari (iPhone), puis choisissez **Ajouter à l'écran d'accueil**. L'application s'ouvre ensuite comme une application normale, même hors ligne avec la dernière édition.

### 7. Activer le bouton « Rafraîchir » (facultatif)
Le bouton demande à GitHub de lancer une édition tout de suite. Il lui faut un jeton d'accès limité à ce seul dépôt :
1. Sur GitHub, cliquez sur votre photo puis **Settings › Developer settings › Personal access tokens › Fine-grained tokens › Generate new token**.
2. Remplissez le formulaire :
   - Nom : `Info du Jour` ;
   - Expiration : 1 an ;
   - **Repository access** : *Only select repositories* › `info-du-jour` ;
   - **Permissions › Repository permissions › Actions** : **Read and write**.
3. Cliquez **Generate token**, puis copiez le jeton (il commence par `github_pat_`).
4. Dans l'application, ouvrez **Réglages › Rafraîchissement à la demande**, collez le jeton, puis cliquez **Enregistrer et tester**.

Le jeton reste sur votre appareil. Il ne permet que de lancer et de suivre les traitements de ce dépôt.

---

## Fonctionnement au quotidien

| Heure (Paris) | Ce qui se passe |
| --- | --- |
| 6 h – 22 h, chaque heure | Collecte des flux RSS ; calcul anticipé des vecteurs des nouveaux articles |
| 15 h et 16 h | Préparation : les résumés IA des sujets qui montent sont rédigés à l'avance (quota réparti) |
| 17 h 30 | Édition : regroupement, classement, rédaction IA, publication (en ligne vers 17 h 45 – 17 h 55) |
| 18 h – 22 h, toutes les 30 min | Rattrapage : l'IA est relancée sur les sujets « Sans IA » ; leur pastille disparaît une fois le résumé obtenu |

Tous ces horaires se règlent dans `config/reglages.yaml`. Le changement d'heure est géré automatiquement. GitHub peut retarder un déclenchement de quelques minutes. Si le créneau de 17 h 30 est manqué, l'édition est lancée au passage suivant.

### Pastilles de traitement
- **IA** (discrète) : résumé rédigé par l'IA et vérifié automatiquement (sources citées, vocabulaire neutre, points de vue équilibrés).
- **⏳ IA en attente** : l'IA n'a pas répondu (quota, panne, délai). Un résumé automatique est affiché, et un nouvel essai est programmé.
- **⚠ Sans IA** : résumé composé d'extraits des articles. Le motif apparaît au survol.
- Le bandeau **« Traitement IA incomplet : X sujets sur Y »** apparaît quand une partie de l'édition est sans IA. Le bandeau **« IA indisponible »** apparaît quand toute l'édition l'est.

### Pluralisme
- Chaque média compte pour une voix, quel que soit son nombre d'articles. Une dépêche d'agence reprise par 8 médias ne compte pas comme 8 confirmations indépendantes.
- Le classement est **calculé**, il n'est pas choisi par l'IA. Il combine 45 % de couverture, 25 % de diversité des orientations, 20 % de fraîcheur et 10 % de reprise par la presse de l'autre périmètre.
- Les tribunes et éditoriaux sont exclus des faits, mais utilisés pour les points de vue.
- La page **Nos sources** affiche le catalogue, l'état des flux et l'équilibre des liens sur 30 éditions, avec une alerte si une sensibilité dépasse 35 % ou passe sous 10 %.
- Le bouton **Signaler un biais** ouvre un signalement dans l'onglet *Issues* du dépôt.

### Personnaliser
Les fichiers de configuration se modifient directement sur GitHub (icône crayon), et chaque changement est daté dans l'historique :

| Fichier | Contenu |
| --- | --- |
| `config/sources.yaml` | médias, orientations, flux, abonnements |
| `config/rubriques.yaml` | rubriques et mots-clés |
| `config/reglages.yaml` | horaires, poids du score, modèles d'IA, édition audio |
| `config/termes_connotes.txt` | vocabulaire refusé dans les résumés IA |
| `config/lexique_debat.txt` | mots qui signalent un débat |

Dans l'application, les **Réglages** permettent de réordonner ou masquer les rubriques, de choisir des mots-clés suivis et le thème. Ces réglages sont propres à chaque appareil.

### Édition audio
Mettez `audio: actif: true` dans `config/reglages.yaml`. Une lecture de l'essentiel et des Tops est alors générée chaque soir par synthèse vocale (Piper, gratuite, sans IA à quota). Elle est proposée en tête d'édition.

---

## Coût et limites
- **Coût : 0 €.** Les dépôts publics ont des minutes GitHub Actions illimitées. Les offres gratuites de Mistral et Gemini suffisent pour environ 10 à 15 appels par édition, car les sujets sont envoyés par lots de 5.
- Les offres gratuites peuvent changer. Si un quota baisse, l'application bascule d'elle-même sur le secours, puis en mode sans IA, sans jamais bloquer l'édition.
- Les requêtes envoyées aux offres gratuites d'IA peuvent servir à entraîner leurs modèles. Il ne s'agit que d'extraits d'articles publics.
- Le site est public mais non référencé (`noindex`). Pour le réserver à la famille, placez-le derrière Cloudflare Access (offre gratuite pour quelques utilisateurs).
- **Droit d'auteur.** L'application affiche des titres et de courts extraits avec lien vers l'article d'origine, comme un lecteur de flux. Elle est prévue pour un usage personnel ou familial. Une diffusion large relèverait du droit voisin des éditeurs de presse.
- **Maintien de la planification.** GitHub suspend les workflows planifiés d'un dépôt public inactif depuis 60 jours. Le workflow se réactive lui-même chaque jour pour l'éviter. Si GitHub envoie malgré tout un courriel de suspension, cliquez **Enable workflow** dans l'onglet Actions.

## Dépannage

| Symptôme | Solution |
| --- | --- |
| La page affiche « Aucune édition publiée » | Lancez **Actions › Info du Jour › Run workflow** et vérifiez que Pages utilise « GitHub Actions » |
| Beaucoup de flux « en échec » dans *Nos sources* | Lancez **Vérifier les flux**, puis corrigez les adresses dans `config/sources.yaml` |
| Tout est « Sans IA » | Vérifiez les secrets `MISTRAL_API_KEY` et `GEMINI_API_KEY`. Les noms de modèles se changent dans `config/reglages.yaml` › `ia` |
| « Rafraîchir » répond « jeton refusé » | Le jeton a expiré ou n'a pas la permission *Actions : Read and write* sur ce dépôt |
| Une exécution est en échec | Onglet **Actions** : le détail de chaque étape indique la cause. GitHub vous prévient aussi par courriel |

## Pour aller plus loin (développeurs)
```bash
pip install -r requirements-dev.txt
python -m pytest -q tests                              # tests automatiques
INFODUJOUR_ETAT=etat-demo python outils/demo.py        # articles fictifs pour essayer hors ligne
INFODUJOUR_ETAT=etat-demo python -m infodujour regrouper
INFODUJOUR_ETAT=etat-demo python -m infodujour rediger
INFODUJOUR_ETAT=etat-demo python -m infodujour publier
INFODUJOUR_ETAT=etat-demo python -m infodujour site --sortie _site
python -m http.server -d _site 8000                    # puis http://localhost:8000
```

| Chemin | Contenu |
| --- | --- |
| `infodujour/` | traitement Python (collecte, regroupement, classement, IA, publication) |
| `site/` | application (HTML, CSS, JavaScript, sans compilation) |
| `config/` | réglages modifiables |
| `.github/workflows/` | planification et mise en ligne |
| `tests/` | tests automatiques |
