-- Migration: store shutdown sequence steps in the order they actually run.
--
-- The executor used to run shutdown sequences in reverse (bottom step first),
-- while the designer showed them top-down as "Execution Order". It now runs
-- every sequence top-down, exactly as listed. This reverses the stored steps of
-- existing shutdown sequences once, so they keep stopping deployments in the
-- same real order and the designer now shows that order.
--
-- One-time data fix, tracked in schema_migrations. Unlike the DDL migrations it
-- is NOT idempotent: do not run it again by hand.

UPDATE environment_sequences AS s
SET steps = (
        SELECT COALESCE(jsonb_agg(x.elem || jsonb_build_object('order', x.rn) ORDER BY x.rn), '[]'::jsonb)
        FROM (
            SELECT t.elem,
                   ROW_NUMBER() OVER (
                       ORDER BY COALESCE((t.elem ->> 'order')::int, 0) DESC, t.pos DESC
                   ) AS rn
            FROM jsonb_array_elements(s.steps) WITH ORDINALITY AS t(elem, pos)
        ) AS x
    ),
    updated_at = NOW()
WHERE s.sequence_type = 'shutdown'
  AND jsonb_typeof(s.steps) = 'array'
  AND jsonb_array_length(s.steps) > 1;
