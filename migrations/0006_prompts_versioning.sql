-- prompts: versioning, and an unambiguous "the prompt for this category".
--
-- Without a uniqueness rule, "the prompt for category X" is whichever row the
-- planner happens to return first. Editing a prompt should add a version and
-- deactivate the old one, not mutate history.

ALTER TABLE prompts
    ADD COLUMN key               VARCHAR(60),
    ADD COLUMN version           INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN max_output_tokens INTEGER NOT NULL DEFAULT 60;

COMMENT ON COLUMN prompts.max_output_tokens IS
    'Per-prompt ceiling on AI response length. A conclusion is one or two '
    'sentences; this is a direct cost control.';

-- Exactly one active prompt per category.
CREATE UNIQUE INDEX idx_prompts_active_per_category
    ON prompts (category_id) WHERE is_active;

-- Give the seeded prompts stable keys derived from their category.
UPDATE prompts p
SET key = c.name || '_trend_v1'
FROM categories c
WHERE c.id = p.category_id AND p.key IS NULL;
