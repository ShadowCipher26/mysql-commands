SET @dev_schema = 'ekyc_kyc_platforms_dev';
SET @qa_schema  = 'idbroker';

-- ============================================
-- PART 1: Table-level differences
-- ============================================
SELECT 
    'TABLE' AS check_type,
    table_name,
    NULL AS column_name,
    NULL AS source_data_type,
    NULL AS target_data_type,
    'dev only' AS status,
    @dev_schema AS source_schema,
    @qa_schema AS target_schema
FROM information_schema.tables
WHERE table_schema = @dev_schema
  AND table_type = 'BASE TABLE'
  AND table_name NOT IN (
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = @qa_schema AND table_type = 'BASE TABLE'
  )

UNION ALL

SELECT 
    'TABLE' AS check_type,
    table_name,
    NULL,
    NULL,
    NULL,
    'qa only' AS status,
    @dev_schema,
    @qa_schema
FROM information_schema.tables
WHERE table_schema = @qa_schema
  AND table_type = 'BASE TABLE'
  AND table_name NOT IN (
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = @dev_schema AND table_type = 'BASE TABLE'
  )

UNION ALL

-- ============================================
-- PART 2: Column-level differences (shared tables)
-- ============================================

-- Type mismatches
SELECT 
    'COLUMN' AS check_type,
    d.table_name,
    d.column_name,
    d.data_type AS dev_type,
    q.data_type AS qa_type,
    'type differs' AS status,
    @dev_schema,
    @qa_schema
FROM information_schema.columns d
JOIN information_schema.columns q
  ON d.table_name = q.table_name AND d.column_name = q.column_name
WHERE d.table_schema = @dev_schema
  AND q.table_schema = @qa_schema
  AND d.data_type <> q.data_type

UNION ALL

-- Columns only in dev's version
SELECT 
    'COLUMN' AS check_type,
    d.table_name,
    d.column_name,
    d.data_type AS dev_type,
    NULL AS qa_type,
    'dev only' AS status,
    @dev_schema,
    @qa_schema
FROM information_schema.columns d
WHERE d.table_schema = @dev_schema
  AND d.table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema = @qa_schema)
  AND d.column_name NOT IN (
      SELECT column_name FROM information_schema.columns
      WHERE table_schema = @qa_schema AND table_name = d.table_name
  )

UNION ALL

-- Columns only in qa's version
SELECT 
    'COLUMN' AS check_type,
    q.table_name,
    q.column_name,
    NULL AS dev_type,
    q.data_type AS qa_type,
    'qa only' AS status,
    @dev_schema,
    @qa_schema
FROM information_schema.columns q
WHERE q.table_schema = @qa_schema
  AND q.table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema = @dev_schema)
  AND q.column_name NOT IN (
      SELECT column_name FROM information_schema.columns
      WHERE table_schema = @dev_schema AND table_name = q.table_name
  )

ORDER BY check_type, table_name, status, column_name;
