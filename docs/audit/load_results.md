# Resultado do teste de carga — SwimTimer

- Data: 2026-10-21 02:25:55
- Python: 3.11.16
- Plataforma: Linux-7.2.11-1-cachyos-x86_64-with-glibc2.44
- SQLite: 3.53.1
- Massa: 5 provas x 4 baterias x 8 raias = 160 raias; 20 equipes

## Criacao de dados
- 20 baterias + 160 raias em 1263 ms (63.1 ms/bateria)

## Endpoints de leitura
- GET /api/events: mediana 23.0 ms, min 19.4 ms, max 26.1 ms, 68.5 KB
- GET /api/events/{id}: mediana 21.0 ms, min 20.4 ms, max 124.9 ms, 68.5 KB
- GET /api/events/{id}/provas: mediana 16.7 ms, min 16.6 ms, max 18.5 ms, 66.1 KB
- GET /api/provas/{id}: mediana 14.6 ms, min 13.9 ms, max 18.1 ms, 13.2 KB
- GET /api/provas/{id}/heats: mediana 24.5 ms, min 16.5 ms, max 32.5 ms, 12.9 KB
- GET /api/provas/{id}/classification: mediana 9.8 ms, min 6.5 ms, max 13.4 ms, 27.8 KB

## Concorrencia (4 baterias da prova 1)
- 32 finalizacoes simultaneas: 32 aceitas, 1114 ms no total (34.8 ms/req)
- classificacao consolidada: 32 validos, 0 excluidos, provisoria=False

## Limites observados
- Teste in-process (ASGI), sem latencia de rede Wi-Fi; numeros servem para comparar regressoes, nao como garantia de producao.
- SQLite em WAL com um unico worker uvicorn: escritas sao serializadas; os locks por bateria evitam corrida no processo.
- Multiplos workers exigiriam banco com concorrencia de escrita (PostgreSQL) ou particionamento; ver docs/ADR/005.
