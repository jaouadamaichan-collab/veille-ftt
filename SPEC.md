# veille-ftt — Spécification

Agent de veille stratégique fondé sur la thèse de Christophe Deschamps (Univ. Poitiers, 2025),
*La phase d'analyse dans le cycle de la veille stratégique*. Principe directeur : la valeur d'une
veille tient à la solidité et à la traçabilité des hypothèses qu'elle produit, pas au volume
d'information traité. Protocole central : **F-T-T — Formuler → Tester → Tracer** (thèse p. 483-487).

Ce document consigne les décisions prises lors de la session de cadrage du 9 novembre 2026.
Toute évolution de ces décisions doit être reportée ici.

---

## 1. Finalité

| # | Décision |
|---|----------|
| D1 | Nouvel agent, conçu autour de F-T-T. `veille-agent` tourne en parallèle ~4 semaines pour comparaison. |
| D2 | Destinataire unique : le propriétaire du dépôt, en position d'analyste/consultant. |
| D8 | Finalité : anticiper les évolutions du secteur pour orienter ses prises de position et repérer des opportunités professionnelles. Le contenu (LinkedIn) est une conséquence, pas une fin. |
| D3/D7 | Domaine pilote unique : **décarbonation du transport maritime**. |
| D4 | Couverture du cycle complet (orientation → collecte → analyse → diffusion → feedback), en version minimale à chaque étape. |

## 2. Répartition des rôles (thèse : puzzles vs mystères, p. 302-304)

| # | Décision |
|---|----------|
| D5 | L'agent **propose** (hypothèses, preuves/contre-preuves, niveau de confiance), l'humain **tranche**. |
| D19 | Cycle de vie d'une hypothèse : `proposee → active → renforcee / affaiblie → archivee`. L'agent peut *suggérer* tout changement ; **seule une action humaine dans le cockpit l'applique**, archivage compris (suggéré après 6 semaines sans signal). |
| D15 | Les hypothèses initiales sont rédigées par l'agent (2 hypothèses + 1 contre-hypothèse par question clé, avec indicateurs) puis validées par l'humain. |

## 3. Cadrage (orientation)

Trois questions clés (D14), fichier `config/domaine.yaml` :

- **Q1 — Carburants** : quelle(s) filière(s) domineront les commandes de navires et contrats d'approvisionnement d'ici 2030 ?
- **Q2 — Régulation** : comment évoluera le cadre (application FuelEU/ETS, révisions UE, sort du Net-Zero Framework OMI) ?
- **Q3 — Acteurs & opportunités** : qui se positionne, et où émergent des besoins adressables ?

Hypothèses initiales : `config/hypotheses_initiales.yaml`.

## 4. Collecte

| # | Décision |
|---|----------|
| D16 | Sources FR + EN, équilibrées entre les trois **échiquiers** (Harbulot, thèse p. 294-296) : concurrentiel, institutionnel, société civile. 15-25 flux RSS au départ + requêtes Serper générées à partir des indicateurs. Fichier `config/sources.yaml`. |
| D17 | Fiabilité par source sur 3 niveaux : `fiable` / `a_confirmer` / `douteuse`, révisable dans le cockpit. |
| D11 | Rythme : collecte + tri **quotidiens** ; analyse F-T-T **hebdomadaire** ; alerte immédiate uniquement si un indicateur d'une hypothèse validée se déclenche. |

## 5. Analyse

| # | Décision |
|---|----------|
| D18 | **Corroboration minimale** : ≥ 2 sources indépendantes de nature différente pour suggérer de renforcer/affaiblir une hypothèse. Une même dépêche reprise = 1 source (détection de reprise par similarité). |
| D23 | **Avocat du diable** hebdomadaire : pour chaque hypothèse active, « qu'est-ce qui la rendrait fausse ? » → requêtes Serper ciblées sur les contre-preuves, avant rédaction du brief. |
| D24 | Étiquetage **échiquier** de chaque signal ; encart « enchaînements inter-échiquiers » dans le brief ; alerte si un échiquier n'a reçu aucun signal pertinent depuis 2 semaines. |
| D25 | **Contrôle anti-hallucination en code** : toute affirmation du brief doit référencer un signal présent en base ; sinon elle est supprimée ou marquée « non sourcé ». |
| D21 | Brief du lundi : **3 mouvements maximum**, chacun en F-T-T. Vocabulaire de vraisemblance fixe : `probable` / `plausible` / `peu probable`. Jamais de verdict. |
| D20 | **Part d'exploration** : 1 à 2 signaux « hors radar » par semaine (pertinents pour le domaine, rattachés à aucune hypothèse). |

## 6. Boucles d'apprentissage

| # | Décision |
|---|----------|
| D22 | Motifs de rejet structurés par élément : `pas_nouveau`, `pas_source`, `hors_sujet`, `mauvaise_lecture`. Retour à **6 semaines** sur chaque hypothèse : « s'est-elle vérifiée ? ». |

## 7. Technique

| # | Décision |
|---|----------|
| D6 | API Claude : Haiku pour le tri quotidien, Sonnet pour l'analyse hebdomadaire. |
| D29 | Plafond 10 €/mois dans la console Anthropic + limite d'appels LLM par exécution dans le code (`MAX_APPELS_LLM`). |
| D10/D28 | Stockage **Supabase**, projet dédié. Accès par clé `service_role` côté serveur uniquement ; RLS activée sans politique publique. |
| D12 | Exécution **GitHub Actions** (cron) dans le dépôt privé `veille-ftt`. Aucun commit depuis les workflows (évite les conflits de rebase rencontrés sur `veille-agent`). |
| D9/D27 | Cockpit **Streamlit** protégé par mot de passe (`st.secrets`). |
| D26 | Alertes par **mail Gmail**, avec lien vers l'hypothèse dans le cockpit. |

## 8. Modèle de données (résumé)

Voir `sql/schema.sql`.

- `sources` — flux et requêtes, échiquier, langue, fiabilité, santé (dernier succès, échecs consécutifs).
- `questions`, `hypotheses`, `hypotheses_versions` (historique complet : traçabilité), `indicateurs`.
- `evenements` — regroupement des signaux traitant du même fait.
- `signaux` — articles collectés, triés, étiquetés (échiquier, questions, hors radar, reprise).
- `liens` — rattachement signal ↔ hypothèse (`soutient` / `contredit`), proposé par l'agent, statué par l'humain.
- `briefs`, `feedbacks` — lots 2 et 3.
- `runs` — journal d'exécution (appels LLM, erreurs).

## 9. Plan de construction

| Lot | Contenu | Critère de fin |
|-----|---------|----------------|
| **1 — Cadrage** | Spec, hypothèses validées, schéma, collecte quotidienne (RSS + Serper), dédoublonnage/reprises, tri Haiku (pertinence, échiquier, rattachement), contrôle de santé des sources | La base se remplit chaque jour de signaux triés et rattachés |
| **2 — Analyse** | Avocat du diable, brief F-T-T hebdo (Sonnet), contrôle des sources citées, cockpit Streamlit de validation | Premier brief du lundi validé dans le cockpit |
| **3 — Boucles** | Alertes indicateurs, part d'exploration, motifs de rejet, retour à 6 semaines | Premier retour à 6 semaines effectué |

## 10. Références dans la thèse

- Protocole F-T-T : p. 483-487
- Cinq habitudes du « maître-penseur », KAC, ACH, pre-mortem : p. 283-290
- Typologie des techniques d'analyse structurées : p. 292-294
- Échiquiers invisibles : p. 294-296
- IA : puzzles vs mystères, trois principes de collaboration : p. 302-314
- Pyramide de la performance analytique (H-O-T) : p. 463-469
