-- Run these functions once in your Supabase SQL editor (Database > SQL Editor).
-- They are called by the frontend via supabase.rpc().
-- Mirrors the exact SQL logic of _search_definitions_raw and _get_definitions_raw in tools.py.

CREATE OR REPLACE FUNCTION deputy_search(
    p_terms          text,
    p_version        text    DEFAULT NULL,
    p_page           integer DEFAULT 1,
    p_page_size      integer DEFAULT 10,
    p_search_aliases boolean DEFAULT true,
    p_search_fqn     boolean DEFAULT true,
    p_use_regex      boolean DEFAULT false,
    p_exact_match    boolean DEFAULT false,
    p_match_case     boolean DEFAULT false,
    p_entity_kinds   text[]  DEFAULT NULL
)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_terms         text[];
    v_lower_terms   text[];
    v_symbols       text[];
    v_dot_term_sfx  text[];
    v_dot_sym_sfx   text[];
    v_sym_sfx       text[];
    v_like_terms    text[];
    v_limit         integer;
    v_offset        integer;
    v_total         bigint;
    v_defs          json;
    v_next_page     integer;
BEGIN
    IF NOT p_search_aliases AND NOT p_search_fqn THEN
        RETURN json_build_object('error', 'At least one of p_search_aliases or p_search_fqn must be true');
    END IF;

    IF p_entity_kinds IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM unnest(p_entity_kinds) k
            WHERE k NOT IN ('module', 'class', 'function', 'method', 'package')
        ) THEN
            RETURN json_build_object('error', 'Invalid entity kind. Valid values: module, class, function, method, package');
        END IF;
    END IF;

    SELECT array_agg(trim(t))
    INTO v_terms
    FROM unnest(string_to_array(p_terms, ',')) t
    WHERE trim(t) <> '';

    IF v_terms IS NULL THEN
        RETURN json_build_object('error', 'No search terms provided');
    END IF;

    SELECT array_agg(reverse(split_part(reverse(t), '.', 1))) INTO v_symbols      FROM unnest(v_terms)   t;
    SELECT array_agg(lower(t))                                INTO v_lower_terms  FROM unnest(v_terms)   t;
    SELECT array_agg('%.' || t)                               INTO v_dot_term_sfx FROM unnest(v_terms)   t;
    SELECT array_agg('%.' || s)                               INTO v_dot_sym_sfx  FROM unnest(v_symbols) s;
    SELECT array_agg('%'  || s)                               INTO v_sym_sfx      FROM unnest(v_symbols) s;
    SELECT array_agg('%'  || t || '%')                        INTO v_like_terms   FROM unnest(v_terms)   t;

    v_limit  := p_page_size;
    v_offset := (p_page - 1) * p_page_size;

    -- Count total ranked matches
    WITH candidates AS (
        SELECT
            e.id   AS entity_id,
            e.name AS fqn,
            e.types,
            a.alias AS matched_alias
        FROM aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE p_search_aliases
          AND (p_entity_kinds IS NULL OR (
              ('module'   = ANY(p_entity_kinds) AND 'MODULE'                 = ANY(e.types))
              OR ('class'    = ANY(p_entity_kinds) AND 'CLASS'                  = ANY(e.types))
              OR ('function' = ANY(p_entity_kinds) AND 'FUNCTION'               = ANY(e.types))
              OR ('method'   = ANY(p_entity_kinds) AND 'METHOD'                 = ANY(e.types))
              OR ('package'  = ANY(p_entity_kinds) AND (
                  'DISTRIBUTION_PACKAGE' = ANY(e.types) OR 'IMPORT_PACKAGE' = ANY(e.types)
              ))
          ))
          AND (p_version IS NULL OR EXISTS (
            SELECT 1 FROM alias_versions av2
            JOIN versions v2 ON v2.id = av2.version_id
            WHERE av2.alias_id = a.id AND v2.version_text = p_version
        ))
        UNION ALL
        SELECT
            e.id   AS entity_id,
            e.name AS fqn,
            e.types,
            NULL::text AS matched_alias
        FROM entities e
        WHERE p_search_fqn
          AND (p_entity_kinds IS NULL OR (
              ('module'   = ANY(p_entity_kinds) AND 'MODULE'                 = ANY(e.types))
              OR ('class'    = ANY(p_entity_kinds) AND 'CLASS'                  = ANY(e.types))
              OR ('function' = ANY(p_entity_kinds) AND 'FUNCTION'               = ANY(e.types))
              OR ('method'   = ANY(p_entity_kinds) AND 'METHOD'                 = ANY(e.types))
              OR ('package'  = ANY(p_entity_kinds) AND (
                  'DISTRIBUTION_PACKAGE' = ANY(e.types) OR 'IMPORT_PACKAGE' = ANY(e.types)
              ))
          ))
    ),
    scored_candidates AS (
        SELECT
            c.entity_id,
            c.fqn,
            c.types,
            COALESCE(c.matched_alias, c.fqn) AS matched_name,
            CASE WHEN c.matched_alias IS NOT NULL THEN 'alias' ELSE 'fqn' END AS match_kind,
            CASE
                -- regex mode: full-exact match scores better than partial
                WHEN p_use_regex AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias ~  ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t))
                                           ELSE c.matched_alias ~* ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t)) END
                ) THEN 5
                WHEN p_use_regex AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn ~  ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t))
                                           ELSE c.fqn ~* ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t)) END
                ) THEN 20
                WHEN p_use_regex AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias ~  ANY(v_terms)
                                           ELSE c.matched_alias ~* ANY(v_terms) END
                ) THEN 20
                WHEN p_use_regex AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn ~  ANY(v_terms)
                                           ELSE c.fqn ~* ANY(v_terms) END
                ) THEN 25
                -- exact-match mode: only exact equality tiers
                WHEN p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)
                                           ELSE lower(c.matched_alias) = ANY(v_lower_terms) END
                ) THEN 5
                WHEN p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)
                                           ELSE lower(c.fqn) = ANY(v_lower_terms) END
                ) THEN 10
                -- normal tiered scoring
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)
                                           ELSE lower(c.matched_alias) = ANY(v_lower_terms) END
                ) THEN 5
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)
                                           ELSE lower(c.fqn) = ANY(v_lower_terms) END
                ) THEN 10
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_term_sfx)
                                           ELSE c.matched_alias ILIKE ANY(v_dot_term_sfx) END
                ) THEN 15
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_term_sfx)
                                           ELSE c.fqn ILIKE ANY(v_dot_term_sfx) END
                ) THEN 20
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_symbols)
                                            ELSE lower(c.matched_alias) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_sym_sfx)
                                               ELSE c.matched_alias ILIKE ANY(v_dot_sym_sfx) END)
                ) THEN 25
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    (CASE WHEN p_match_case THEN c.fqn = ANY(v_symbols)
                                            ELSE lower(c.fqn) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_sym_sfx)
                                               ELSE c.fqn ILIKE ANY(v_dot_sym_sfx) END)
                ) THEN 30
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_sym_sfx)
                                           ELSE c.matched_alias ILIKE ANY(v_sym_sfx) END
                ) THEN 35
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_sym_sfx)
                                           ELSE c.fqn ILIKE ANY(v_sym_sfx) END
                ) THEN 40
                ELSE 50
            END AS score
        FROM candidates c
        JOIN entity_versions ev ON ev.entity_id = c.entity_id
        JOIN versions v ON v.id = ev.version_id
        WHERE (
            -- regex filter
            (p_use_regex AND (
                (c.matched_alias IS NOT NULL AND (CASE WHEN p_match_case THEN c.matched_alias ~  ANY(v_terms) ELSE c.matched_alias ~* ANY(v_terms) END))
                OR (c.fqn IS NOT NULL AND (CASE WHEN p_match_case THEN c.fqn ~  ANY(v_terms) ELSE c.fqn ~* ANY(v_terms) END))
            ))
            -- exact-match filter
            OR (p_exact_match AND NOT p_use_regex AND (
                (c.matched_alias IS NOT NULL AND (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms) ELSE lower(c.matched_alias) = ANY(v_lower_terms) END))
                OR (CASE WHEN p_match_case THEN c.fqn = ANY(v_terms) ELSE lower(c.fqn) = ANY(v_lower_terms) END)
            ))
            -- normal tiered filter
            OR (NOT p_use_regex AND NOT p_exact_match AND (
                (c.matched_alias IS NOT NULL AND (
                    (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)             ELSE lower(c.matched_alias) = ANY(v_lower_terms) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_term_sfx) ELSE c.matched_alias ILIKE ANY(v_dot_term_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_symbols)         ELSE lower(c.matched_alias) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_sym_sfx)  ELSE c.matched_alias ILIKE ANY(v_dot_sym_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_sym_sfx)      ELSE c.matched_alias ILIKE ANY(v_sym_sfx) END)
                    OR c.matched_alias ILIKE ANY(v_like_terms)
                ))
                OR (
                    (CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)             ELSE lower(c.fqn) = ANY(v_lower_terms) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_term_sfx) ELSE c.fqn ILIKE ANY(v_dot_term_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.fqn = ANY(v_symbols)         ELSE lower(c.fqn) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_sym_sfx)  ELSE c.fqn ILIKE ANY(v_dot_sym_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_sym_sfx)      ELSE c.fqn ILIKE ANY(v_sym_sfx) END)
                    OR c.fqn ILIKE ANY(v_like_terms)
                )
            ))
        )
        AND (p_version IS NULL OR v.version_text = p_version)
    ),
    best_per_entity AS (
        SELECT DISTINCT ON (entity_id)
            entity_id, fqn, types, matched_name, match_kind, score
        FROM scored_candidates
        WHERE score < 50
        ORDER BY entity_id, score ASC, match_kind ASC
    ),
    ranked_matches AS (
        SELECT entity_id, fqn, types, matched_name, match_kind, score,
               MIN(CASE WHEN fqn = ANY(v_terms) THEN 0 ELSE 1 END)
                   OVER (PARTITION BY entity_id) AS fqn_exact
        FROM best_per_entity
    )
    SELECT COUNT(*) INTO v_total FROM ranked_matches;

    -- Paginated results with community members
    WITH candidates AS (
        SELECT
            e.id   AS entity_id,
            e.name AS fqn,
            e.types,
            a.alias AS matched_alias
        FROM aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE p_search_aliases
          AND (p_entity_kinds IS NULL OR (
              ('module'   = ANY(p_entity_kinds) AND 'MODULE'                 = ANY(e.types))
              OR ('class'    = ANY(p_entity_kinds) AND 'CLASS'                  = ANY(e.types))
              OR ('function' = ANY(p_entity_kinds) AND 'FUNCTION'               = ANY(e.types))
              OR ('method'   = ANY(p_entity_kinds) AND 'METHOD'                 = ANY(e.types))
              OR ('package'  = ANY(p_entity_kinds) AND (
                  'DISTRIBUTION_PACKAGE' = ANY(e.types) OR 'IMPORT_PACKAGE' = ANY(e.types)
              ))
          ))
          AND (p_version IS NULL OR EXISTS (
            SELECT 1 FROM alias_versions av2
            JOIN versions v2 ON v2.id = av2.version_id
            WHERE av2.alias_id = a.id AND v2.version_text = p_version
        ))
        UNION ALL
        SELECT
            e.id   AS entity_id,
            e.name AS fqn,
            e.types,
            NULL::text AS matched_alias
        FROM entities e
        WHERE p_search_fqn
          AND (p_entity_kinds IS NULL OR (
              ('module'   = ANY(p_entity_kinds) AND 'MODULE'                 = ANY(e.types))
              OR ('class'    = ANY(p_entity_kinds) AND 'CLASS'                  = ANY(e.types))
              OR ('function' = ANY(p_entity_kinds) AND 'FUNCTION'               = ANY(e.types))
              OR ('method'   = ANY(p_entity_kinds) AND 'METHOD'                 = ANY(e.types))
              OR ('package'  = ANY(p_entity_kinds) AND (
                  'DISTRIBUTION_PACKAGE' = ANY(e.types) OR 'IMPORT_PACKAGE' = ANY(e.types)
              ))
          ))
    ),
    scored_candidates AS (
        SELECT
            c.entity_id,
            c.fqn,
            c.types,
            COALESCE(c.matched_alias, c.fqn) AS matched_name,
            CASE WHEN c.matched_alias IS NOT NULL THEN 'alias' ELSE 'fqn' END AS match_kind,
            CASE
                WHEN p_use_regex AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias ~  ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t))
                                           ELSE c.matched_alias ~* ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t)) END
                ) THEN 5
                WHEN p_use_regex AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn ~  ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t))
                                           ELSE c.fqn ~* ANY(array(SELECT '^(?:' || t || ')$' FROM unnest(v_terms) t)) END
                ) THEN 20
                WHEN p_use_regex AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias ~  ANY(v_terms)
                                           ELSE c.matched_alias ~* ANY(v_terms) END
                ) THEN 20
                WHEN p_use_regex AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn ~  ANY(v_terms)
                                           ELSE c.fqn ~* ANY(v_terms) END
                ) THEN 25
                WHEN p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)
                                           ELSE lower(c.matched_alias) = ANY(v_lower_terms) END
                ) THEN 5
                WHEN p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)
                                           ELSE lower(c.fqn) = ANY(v_lower_terms) END
                ) THEN 10
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)
                                           ELSE lower(c.matched_alias) = ANY(v_lower_terms) END
                ) THEN 5
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)
                                           ELSE lower(c.fqn) = ANY(v_lower_terms) END
                ) THEN 10
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_term_sfx)
                                           ELSE c.matched_alias ILIKE ANY(v_dot_term_sfx) END
                ) THEN 15
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_term_sfx)
                                           ELSE c.fqn ILIKE ANY(v_dot_term_sfx) END
                ) THEN 20
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_symbols)
                                            ELSE lower(c.matched_alias) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_sym_sfx)
                                               ELSE c.matched_alias ILIKE ANY(v_dot_sym_sfx) END)
                ) THEN 25
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    (CASE WHEN p_match_case THEN c.fqn = ANY(v_symbols)
                                            ELSE lower(c.fqn) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_sym_sfx)
                                               ELSE c.fqn ILIKE ANY(v_dot_sym_sfx) END)
                ) THEN 30
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NOT NULL AND (
                    CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_sym_sfx)
                                           ELSE c.matched_alias ILIKE ANY(v_sym_sfx) END
                ) THEN 35
                WHEN NOT p_use_regex AND NOT p_exact_match AND c.matched_alias IS NULL AND (
                    CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_sym_sfx)
                                           ELSE c.fqn ILIKE ANY(v_sym_sfx) END
                ) THEN 40
                ELSE 50
            END AS score
        FROM candidates c
        JOIN entity_versions ev ON ev.entity_id = c.entity_id
        JOIN versions v ON v.id = ev.version_id
        WHERE (
            (p_use_regex AND (
                (c.matched_alias IS NOT NULL AND (CASE WHEN p_match_case THEN c.matched_alias ~  ANY(v_terms) ELSE c.matched_alias ~* ANY(v_terms) END))
                OR (c.fqn IS NOT NULL AND (CASE WHEN p_match_case THEN c.fqn ~  ANY(v_terms) ELSE c.fqn ~* ANY(v_terms) END))
            ))
            OR (p_exact_match AND NOT p_use_regex AND (
                (c.matched_alias IS NOT NULL AND (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms) ELSE lower(c.matched_alias) = ANY(v_lower_terms) END))
                OR (CASE WHEN p_match_case THEN c.fqn = ANY(v_terms) ELSE lower(c.fqn) = ANY(v_lower_terms) END)
            ))
            OR (NOT p_use_regex AND NOT p_exact_match AND (
                (c.matched_alias IS NOT NULL AND (
                    (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_terms)             ELSE lower(c.matched_alias) = ANY(v_lower_terms) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_term_sfx) ELSE c.matched_alias ILIKE ANY(v_dot_term_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias = ANY(v_symbols)         ELSE lower(c.matched_alias) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_dot_sym_sfx)  ELSE c.matched_alias ILIKE ANY(v_dot_sym_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.matched_alias LIKE ANY(v_sym_sfx)      ELSE c.matched_alias ILIKE ANY(v_sym_sfx) END)
                    OR c.matched_alias ILIKE ANY(v_like_terms)
                ))
                OR (
                    (CASE WHEN p_match_case THEN c.fqn = ANY(v_terms)             ELSE lower(c.fqn) = ANY(v_lower_terms) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_term_sfx) ELSE c.fqn ILIKE ANY(v_dot_term_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.fqn = ANY(v_symbols)         ELSE lower(c.fqn) = ANY(array(SELECT lower(s) FROM unnest(v_symbols) s)) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_dot_sym_sfx)  ELSE c.fqn ILIKE ANY(v_dot_sym_sfx) END)
                    OR (CASE WHEN p_match_case THEN c.fqn LIKE ANY(v_sym_sfx)      ELSE c.fqn ILIKE ANY(v_sym_sfx) END)
                    OR c.fqn ILIKE ANY(v_like_terms)
                )
            ))
        )
        AND (p_version IS NULL OR v.version_text = p_version)
    ),
    -- Pick the best-scoring match per entity to use as primary
    best_per_entity AS (
        SELECT DISTINCT ON (entity_id)
            entity_id, fqn, types, matched_name, match_kind, score
        FROM scored_candidates
        WHERE score < 50
        ORDER BY entity_id, score ASC, match_kind ASC
    ),
    ranked_matches AS (
        SELECT entity_id, fqn, types, matched_name, match_kind, score,
               CASE WHEN lower(matched_name) = ANY(v_lower_terms) THEN 0 ELSE 1 END AS name_exact,
               length(matched_name) AS name_length
        FROM best_per_entity
    ),
    paginated AS (
        SELECT entity_id, fqn, types, matched_name, match_kind, score, name_exact, name_length
        FROM ranked_matches
        ORDER BY score ASC, name_exact ASC, name_length ASC, matched_name ASC, fqn ASC
        LIMIT v_limit OFFSET v_offset
    ),
    -- Build the community members: FQN + all version-filtered aliases, each tagged with kind.
    -- Primary (best-scoring) member is excluded from members list; it is output separately.
    with_members AS (
        SELECT
            p.entity_id,
            p.fqn,
            p.types,
            p.score,
            p.matched_name  AS primary_name,
            p.match_kind    AS primary_kind,
            p.score         AS sort_score,
            p.name_exact    AS sort_name_exact,
            p.name_length   AS sort_name_length,
            COALESCE(
                json_agg(
                    json_build_object(
                        'name', m.member_name,
                        'kind', m.member_kind
                    )
                    ORDER BY
                        -- matched-to-search terms first, then by length
                        CASE WHEN lower(m.member_name) = ANY(v_lower_terms) THEN 0 ELSE 1 END,
                        length(m.member_name)
                ) FILTER (WHERE m.member_name IS NOT NULL AND m.member_name <> p.matched_name),
                '[]'::json
            ) AS members
        FROM paginated p
        LEFT JOIN LATERAL (
            -- fqn as a member
            SELECT p.fqn AS member_name, 'fqn'::text AS member_kind
            UNION ALL
            -- all version-filtered aliases as members
            SELECT a.alias AS member_name, 'alias'::text AS member_kind
            FROM aliases a
            WHERE a.entity_id = p.entity_id
              AND (p_version IS NULL OR EXISTS (
                SELECT 1 FROM alias_versions av3
                JOIN versions v3 ON v3.id = av3.version_id
                WHERE av3.alias_id = a.id AND v3.version_text = p_version
              ))
        ) m ON true
        GROUP BY p.entity_id, p.fqn, p.types, p.score, p.name_exact, p.name_length, p.matched_name, p.match_kind
    )
    SELECT COALESCE(json_agg(json_build_object(
        'labels',   wm.types,
        'primary',  json_build_object('name', wm.primary_name, 'kind', wm.primary_kind),
        'members',  wm.members
    ) ORDER BY wm.sort_score ASC, wm.sort_name_exact ASC, wm.sort_name_length ASC, wm.primary_name ASC, wm.fqn ASC), '[]'::json)
    INTO v_defs
    FROM with_members wm;

    v_next_page := CASE WHEN v_total > p_page * p_page_size THEN p_page + 1 ELSE NULL END;

    RETURN json_build_object(
        'definitions',   v_defs,
        'current_page',  p_page,
        'total_results', v_total,
        'next_page',     v_next_page
    );
END;
$$;


CREATE OR REPLACE FUNCTION deputy_definitions(
    p_names   text,
    p_version text    DEFAULT NULL,
    p_fields  text[]  DEFAULT '{source}'::text[]
)
RETURNS json
LANGUAGE sql
SECURITY DEFINER
AS $$
-- Mirrors _get_definitions_raw in tools.py.
-- p_fields controls which data is returned. Supported values:
--   'source'    - full_source (source_code column); required for line-based extraction in buildDefinition()
--   'signature' - signature_start_line, signature_end_line
--   'docstring' - module_docstring / docstring_start_line, docstring_end_line
--   'file_info' - file_path, start_line, end_line
-- The TypeScript buildDefinition() in tools.ts handles context/source slicing from line numbers.
WITH entity_names AS (
    SELECT trim(n) AS entity_name
    FROM unnest(string_to_array(p_names, ',')) n
    WHERE trim(n) <> ''
),
version_filter AS (
    SELECT id AS version_id
    FROM versions
    WHERE (p_version IS NULL) OR (version_text = p_version)
),
module_rows AS (
    SELECT DISTINCT ON (e.id)
        e.id                                                                              AS entity_id,
        e.name,
        e.types,
        CASE WHEN 'source'    = ANY(p_fields) THEN ms.source_code    ELSE NULL END        AS full_source,
        CASE WHEN 'docstring' = ANY(p_fields) THEN ms.docstring      ELSE NULL END        AS module_docstring,
        CASE WHEN 'file_info' = ANY(p_fields) THEN ms.file_path      ELSE NULL END        AS file_path,
        NULL::int                                                                          AS start_line,
        NULL::int                                                                          AS end_line,
        NULL::int                                                                          AS docstring_start_line,
        NULL::int                                                                          AS docstring_end_line,
        NULL::int                                                                          AS signature_start_line,
        NULL::int                                                                          AS signature_end_line
    FROM entities e
    JOIN entity_names        en  ON en.entity_name = e.name
    JOIN module_sources      ms  ON ms.module_entity_id = e.id
    JOIN module_source_versions msv ON msv.module_source_id = ms.id
    JOIN version_filter      vf  ON vf.version_id = msv.version_id
    WHERE 'MODULE' = ANY(e.types)
    ORDER BY e.id, msv.version_id DESC, ms.id DESC
),
definition_rows AS (
    SELECT DISTINCT ON (e.id, ed.id)
        e.id                                                                              AS entity_id,
        e.name,
        e.types,
        CASE WHEN 'source'    = ANY(p_fields) THEN ms.source_code    ELSE NULL END        AS full_source,
        NULL::text                                                                         AS module_docstring,
        CASE WHEN 'file_info' = ANY(p_fields) THEN ms.file_path      ELSE NULL END        AS file_path,
        CASE WHEN 'file_info' = ANY(p_fields) THEN loc.start_line    ELSE NULL END        AS start_line,
        CASE WHEN 'file_info' = ANY(p_fields) THEN loc.end_line      ELSE NULL END        AS end_line,
        CASE WHEN 'docstring' = ANY(p_fields) THEN loc.docstring_start_line ELSE NULL END AS docstring_start_line,
        CASE WHEN 'docstring' = ANY(p_fields) THEN loc.docstring_end_line   ELSE NULL END AS docstring_end_line,
        CASE WHEN 'signature' = ANY(p_fields) THEN loc.signature_start_line ELSE NULL END AS signature_start_line,
        CASE WHEN 'signature' = ANY(p_fields) THEN loc.signature_end_line   ELSE NULL END AS signature_end_line
    FROM entities e
    JOIN entity_names                 en  ON en.entity_name = e.name
    JOIN entity_definitions           ed  ON ed.entity_id = e.id
    JOIN entity_definition_locations  loc ON loc.definition_id = ed.id
    JOIN module_sources               ms  ON ms.id = loc.module_source_id
    JOIN version_filter               vf  ON vf.version_id = loc.version_id
    WHERE NOT ('MODULE' = ANY(e.types))
    ORDER BY e.id, ed.id, loc.version_id DESC
)
SELECT COALESCE(json_agg(row_to_json(x.*) ORDER BY x.name), '[]'::json)
FROM (
    SELECT * FROM module_rows
    UNION ALL
    SELECT * FROM definition_rows
) x;
$$;
