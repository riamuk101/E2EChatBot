-- import_function.sql
INSERT INTO "function" (
    "id", "user_id", "name", "type", "content", "meta", 
    "created_at", "updated_at", "valves", "is_active", "is_global"
) VALUES (
    'n8n', ?, 'n8n', 'pipe', 
    ?, 
    '{"description": "n8n", "manifest": {}}',
    strftime('%s', 'now'), strftime('%s', 'now'), 
    'null', 1, 0
);