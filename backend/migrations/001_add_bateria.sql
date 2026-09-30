-- SwimTimer — migração 001: modo "Bateria Cronometrada"
-- Adiciona colunas sem perder dados existentes.
-- SQLite não suporta "ADD COLUMN IF NOT EXISTS"; a aplicação executa esta
-- migração de forma idempotente (ver _apply_migrations em app/database.py).
-- Este script é a versão manual equivalente.

ALTER TABLE competition ADD COLUMN event_type TEXT NOT NULL DEFAULT 'maratona';
ALTER TABLE competition ADD COLUMN distance_m INTEGER DEFAULT 25;

ALTER TABLE lane ADD COLUMN participant_name TEXT;
ALTER TABLE lane ADD COLUMN finish_at REAL;
ALTER TABLE lane ADD COLUMN race_time_ms INTEGER;
