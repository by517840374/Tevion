-- Creates a separate test database so tests never touch development data.
SELECT 'CREATE DATABASE tevion_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'tevion_test')
\gexec
