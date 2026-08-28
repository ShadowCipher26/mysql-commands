-- Columns with a different data type in shared tables
SELECT d.table_name, d.column_name, d.data_type AS dev_type, q.data_type AS qa_type, 'type differs' AS status
FROM information_schema.columns d
JOIN information_schema.columns q
  ON d.table_name = q.table_name AND d.column_name = q.column_name
WHERE d.table_schema = 'a'
  AND q.table_schema = 'b'
  AND d.data_type <> q.data_type

UNION ALL

-- Columns only in dev's version of a shared table
SELECT d.table_name, d.column_name, d.data_type AS dev_type, NULL AS qa_type, 'dev only' AS status
FROM information_schema.columns d
WHERE d.table_schema = 'a'
  AND d.table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema = 'b')
  AND d.column_name NOT IN (
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'b' AND table_name = d.table_name
  )

UNION ALL

-- Columns only in qa's version of a shared table
SELECT q.table_name, q.column_name, NULL AS dev_type, q.data_type AS qa_type, 'qa only' AS status
FROM information_schema.columns q
WHERE q.table_schema = 'b'
  AND q.table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema = 'a')
  AND q.column_name NOT IN (
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'a' AND table_name = q.table_name
  )

ORDER BY table_name, status, column_name;
