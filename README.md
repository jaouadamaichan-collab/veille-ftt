# veille-ftt

Agent de veille stratégique — décarbonation du transport maritime — fondé sur le protocole
**Formuler → Tester → Tracer** (thèse de C. Deschamps, 2025). Décisions de conception : [SPEC.md](SPEC.md).

**État : lots 1 (cadrage, collecte quotidienne) et 2 (brief F-T-T du lundi, cockpit).** Lot 3 (alertes sur indicateurs, retour à 6 semaines) à venir.

## Fonctionnement du lot 1

Chaque matin (GitHub Actions, 6h41 heure de Paris en hiver) :

1. **Collecte** : flux RSS + recherches Serper (sources institutionnelles et requêtes des indicateurs, en rotation sur 3 jours). Si Serper refuse (crédits épuisés, clé invalide), le passage bascule automatiquement sur DuckDuckGo.
2. **Dédoublonnage** : même URL ou même article → ignoré ; même dépêche reprise ailleurs → marquée *reprise* (ne compte pas comme source indépendante) ; même fait rédigé autrement → même *événement*.
3. **Pré-filtre** sans IA par mots-clés du domaine.
4. **Tri Haiku** : pertinence, score, échiquier, questions clés, et *propositions* de rattachement aux hypothèses (soutient / contredit), avec la justification factuelle. Les identifiants inventés par le modèle sont filtrés en code.
5. Tout est écrit dans Supabase. Aucun commit dans le dépôt.

## Le brief du lundi (lot 2)

Chaque lundi (7h23 heure de Paris en hiver), après la collecte :

1. **Avocat du diable** (Sonnet) : pour chaque hypothèse active, ce qui la rendrait fausse, et 1-2 requêtes pour le chercher.
2. Collecte et tri de ces **contre-preuves**.
3. **Dossier calculé en code** : preuves par hypothèse, corroboration (≥ 2 sources indépendantes de nature différente), échiquiers silencieux depuis 14 jours, candidats hors radar, hypothèses sans signal depuis 6 semaines.
4. **Brief F-T-T** (Sonnet) : 3 mouvements au plus, chacun en Formuler / Tester / Tracer, vocabulaire probable / plausible / peu probable.
5. **Contrôle en code** : tout élément de preuve sans signal du dossier est retiré, toute référence inventée est remplacée par « [non sourcé] », toute suggestion « renforcée / affaiblie » sans corroboration suffisante est ramenée à « maintenir ».
6. Enregistrement en brouillon et **envoi par mail** avec le lien du cockpit.

L'agent ne change jamais un statut : il suggère, l'analyste tranche dans le cockpit.

## Le cockpit

Application Streamlit (`cockpit/app.py`) : brief et décisions à prendre, registre des hypothèses (statut, vraisemblance,
reformulation, historique, ajout), liens proposés à valider ou rejeter avec motif, réglage des sources, journal des exécutions.

Déploiement sur [share.streamlit.io](https://share.streamlit.io) : *New app* → dépôt `veille-ftt`, branche `main`,
*Main file path* `cockpit/app.py` → *Advanced settings → Secrets* :

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_SERVICE_KEY = "sb_secret_..."
MOT_DE_PASSE = "choisissez-un-mot-de-passe"
```

Si un secret manque, l'application affiche lesquels elle ne trouve pas.

## Mise en route (une fois)

1. **Supabase** : créer un nouveau projet → *SQL Editor* → coller `sql/schema.sql` → *Run*.
   Récupérer dans *Settings → API* l'URL du projet et la clé **service_role** (pas la clé anon).
2. **Anthropic** : dans la console, fixer un plafond de dépense mensuel (10 €).
3. **GitHub** → dépôt → *Settings → Secrets and variables → Actions* → ajouter :
   | Secret | Valeur |
   |---|---|
   | `ANTHROPIC_API_KEY` | clé API Claude |
   | `SERPER_API_KEY` | clé serper.dev |
   | `SUPABASE_URL` | `https://<projet>.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | clé service_role |
   | `GMAIL_EXPEDITEUR` | adresse Gmail d'envoi (brief du lundi) |
   | `GMAIL_MOT_DE_PASSE` | mot de passe d'application Gmail |
   | `GMAIL_DESTINATAIRE` | facultatif, sinon l'expéditeur |

   Et dans l'onglet *Variables* : `COCKPIT_URL` = l'adresse du cockpit Streamlit (lien dans le mail).
4. **Actions → Maintenance → Run workflow** :
   - `import-config` : importe questions, hypothèses (statut *proposee*), indicateurs et sources ;
   - `sante-sources` : teste chaque flux RSS et affiche un tableau dans le résumé de l'exécution ;
   - `activer-hypotheses-proposees` : passe les hypothèses *proposee* en *active* (décision humaine historisée), en attendant le cockpit.
5. **Actions → Veille quotidienne → Run workflow** pour un premier passage manuel.

## Réglages (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_APPELS_LLM` | 40 | Plafond d'appels Claude par exécution |
| `MAX_REQUETES_SERPER` | 20 | Plafond de recherches Serper par exécution |
| `TAILLE_LOT_TRI` | 10 | Articles par appel de tri |
| `MODELE_TRI` | `claude-haiku-4-5-20251001` | Modèle de tri quotidien |
| `JOURS_FENETRE` | 7 | Fenêtre de collecte et de rapprochement |
| `PAUSE_DDG` | 2 | Pause (s) entre deux recherches DuckDuckGo |

## Modifier le cadrage

Les fichiers `config/*.yaml` sont la source de départ. L'import **n'écrase jamais** une hypothèse ou une
source déjà en base (les modifications faites dans le cockpit priment). Pour ajouter une hypothèse :
l'ajouter au YAML puis relancer `import-config`. `python -m pytest` vérifie la cohérence du cadrage
(2 hypothèses + 1 contre-hypothèse par question, indicateurs qui confirment ET infirment, vocabulaire fixe).

## Développement local

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # tests hors ligne, sans clé
```
