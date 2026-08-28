SELECT 
    table_name, 'dev only' AS status
FROM
    information_schema.tables
WHERE
    table_schema = 'a'
        AND table_type = 'BASE TABLE'
        AND table_name NOT IN (SELECT 
            table_name
        FROM
            information_schema.tables
        WHERE
            table_schema = 'b'
                AND table_type = 'BASE TABLE') 
UNION ALL SELECT 
    table_name, 'qa only' AS status
FROM
    information_schema.tables
WHERE
    table_schema = 'b'
        AND table_type = 'BASE TABLE'
        AND table_name NOT IN (SELECT 
            table_name
        FROM
            information_schema.tables
        WHERE
            table_schema = 'a'
                AND table_type = 'BASE TABLE')
ORDER BY status , table_name;
