-- veille-ftt — schéma Supabase (PostgreSQL)
-- À exécuter une fois dans SQL Editor du projet Supabase dédié (D28).
-- Accès : clé service_role côté serveur uniquement (GitHub Actions, Streamlit). RLS activée
-- sur toutes les tables, sans politique : la clé anon publique n'a donc accès à rien.

-- ───────────── Référentiels ─────────────

create table if not exists sources (
    id                  text primary key,
    nom                 text not null,
    type                text not null check (type in ('rss', 'serper')),
    url                 text,
    requete             text,
    echiquier           text not null check (echiquier in ('concurrentiel', 'institutionnel', 'societe_civile')),
    langue              text not null default 'en',
    fiabilite           text not null default 'a_confirmer' check (fiabilite in ('fiable', 'a_confirmer', 'douteuse')),
    actif               boolean not null default true,
    verifie             boolean not null default false,
    derniere_reussite   timestamptz,
    echecs_consecutifs  int not null default 0,
    derniere_erreur     text
);

create table if not exists questions (
    id                  text primary key,
    intitule            text not null,
    echiquier_principal text
);

create table if not exists hypotheses (
    id                  text primary key,
    question_id         text not null references questions(id),
    type                text not null check (type in ('hypothese', 'contre')),
    enonce              text not null,
    contexte            text,
    statut              text not null default 'proposee'
                        check (statut in ('proposee', 'active', 'renforcee', 'affaiblie', 'archivee')),
    confiance           text check (confiance in ('probable', 'plausible', 'peu probable')),
    cree_le             timestamptz not null default now(),
    maj_le              timestamptz not null default now(),
    dernier_signal_le   timestamptz
);

-- Traçabilité (T de F-T-T) : chaque changement d'énoncé, de statut ou de confiance est historisé.
create table if not exists hypotheses_versions (
    id                  bigserial primary key,
    hypothese_id        text not null references hypotheses(id),
    enonce              text not null,
    statut              text not null,
    confiance           text,
    motif               text,
    auteur              text not null check (auteur in ('humain', 'agent')),
    cree_le             timestamptz not null default now()
);

create table if not exists indicateurs (
    id                  text primary key,
    hypothese_id        text not null references hypotheses(id),
    description         text not null,
    sens                text not null check (sens in ('confirme', 'infirme')),
    requete             text,
    actif               boolean not null default true,
    dernier_declenchement timestamptz
);

-- ───────────── Collecte ─────────────

-- Un événement regroupe les signaux traitant du même fait (corroboration, D18).
create table if not exists evenements (
    id                  bigserial primary key,
    titre_ref           text not null,
    premier_vu          timestamptz not null default now(),
    dernier_vu          timestamptz not null default now()
);

create table if not exists signaux (
    id                  bigserial primary key,
    url                 text not null,
    url_norm            text not null unique,
    titre               text not null,
    extrait             text,
    source_id           text references sources(id),
    origine             text,                            -- 'rss' | 'serper' | 'indicateur:<id>' (requête ciblée)
    domaine             text,
    langue              text,
    publie_le           timestamptz,
    collecte_le         timestamptz not null default now(),
    evenement_id        bigint references evenements(id),
    reprise_de          bigint references signaux(id),   -- même dépêche reprise : ne compte pas comme source indépendante
    -- Tri (Haiku)
    trie                boolean not null default false,
    pertinent           boolean,
    score               int check (score between 0 and 10),
    echiquier           text check (echiquier in ('concurrentiel', 'institutionnel', 'societe_civile')),
    questions           text[] default '{}',
    resume              text,
    hors_radar          boolean not null default false,
    triage_brut         jsonb
);
create index if not exists signaux_collecte_idx on signaux (collecte_le desc);
create index if not exists signaux_evenement_idx on signaux (evenement_id);
create index if not exists signaux_non_tries_idx on signaux (trie) where trie = false;

-- Rattachement signal ↔ hypothèse, proposé par l'agent, statué par l'humain (D5).
create table if not exists liens (
    id                  bigserial primary key,
    signal_id           bigint not null references signaux(id) on delete cascade,
    hypothese_id        text not null references hypotheses(id),
    indicateur_id       text references indicateurs(id),
    relation            text not null check (relation in ('soutient', 'contredit')),
    justification       text,
    statut              text not null default 'propose' check (statut in ('propose', 'valide', 'rejete')),
    motif_rejet         text check (motif_rejet in ('pas_nouveau', 'pas_source', 'hors_sujet', 'mauvaise_lecture')),
    cree_le             timestamptz not null default now(),
    unique (signal_id, hypothese_id)
);

-- Vue de corroboration : nombre de sources indépendantes par événement (hors reprises).
create or replace view evenements_corroboration as
select
    e.id as evenement_id,
    e.titre_ref,
    count(distinct s.domaine) filter (where s.reprise_de is null)                  as nb_domaines_independants,
    count(distinct src.echiquier) filter (where s.reprise_de is null)              as nb_echiquiers,
    count(distinct src.type)      filter (where s.reprise_de is null)              as nb_types_source,
    count(*)                                                                       as nb_signaux,
    min(s.collecte_le) as premier_vu,
    max(s.collecte_le) as dernier_vu
from evenements e
join signaux s on s.evenement_id = e.id
left join sources src on src.id = s.source_id
group by e.id, e.titre_ref;

-- ───────────── Lots 2 et 3 (créés dès maintenant pour éviter les migrations) ─────────────

create table if not exists briefs (
    id                  bigserial primary key,
    semaine             date not null unique,          -- lundi de la semaine
    contenu             jsonb not null,                -- mouvements F-T-T structurés
    markdown            text,
    statut              text not null default 'brouillon' check (statut in ('brouillon', 'valide')),
    cree_le             timestamptz not null default now()
);

create table if not exists feedbacks (
    id                  bigserial primary key,
    cible_type          text not null check (cible_type in ('signal', 'lien', 'mouvement', 'hypothese')),
    cible_id            text not null,
    verdict             text not null check (verdict in ('utile', 'partiel', 'rejete', 'verifiee', 'infirmee', 'indeterminee')),
    motif               text check (motif in ('pas_nouveau', 'pas_source', 'hors_sujet', 'mauvaise_lecture')),
    note                text,
    cree_le             timestamptz not null default now()
);

-- ───────────── Journal d'exécution ─────────────

create table if not exists runs (
    id                  bigserial primary key,
    type                text not null,                 -- daily | weekly | check_sources | seed
    debut               timestamptz not null default now(),
    fin                 timestamptz,
    statut              text not null default 'en_cours' check (statut in ('en_cours', 'ok', 'partiel', 'erreur')),
    nb_collectes        int default 0,
    nb_nouveaux         int default 0,
    nb_tries            int default 0,
    nb_appels_llm       int default 0,
    nb_requetes_serper  int default 0,
    erreurs             jsonb default '[]'::jsonb
);

-- ───────────── Sécurité ─────────────
alter table sources              enable row level security;
alter table questions            enable row level security;
alter table hypotheses           enable row level security;
alter table hypotheses_versions  enable row level security;
alter table indicateurs          enable row level security;
alter table evenements           enable row level security;
alter table signaux              enable row level security;
alter table liens                enable row level security;
alter table briefs               enable row level security;
alter table feedbacks            enable row level security;
alter table runs                 enable row level security;
-- La vue hérite des droits de son propriétaire ; on la restreint explicitement.
alter view evenements_corroboration set (security_invoker = true);
