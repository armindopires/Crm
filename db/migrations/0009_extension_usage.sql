-- WE · 0009 · Tipos/operadores de extensões (pgvector) vivem em public: uso sem privilégio de criação.
GRANT USAGE ON SCHEMA public TO we_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
