# Resultado do teste de carga — SwimTimer

- Data: 2026-10-23 00:07:01
- Python: 3.11.16
- Plataforma: Linux-7.2.11-1-cachyos-x86_64-with-glibc2.44
- SQLite: 3.53.1
- Massa: 8 provas x 50 baterias x 8 raias = 400 raias; 8 equipes; 150 atletas importados

## Importacao de atletas
- 150 atletas e 0 equipes em 17 ms (0.11 ms/atleta), 0 erros
- listagem paginada: mediana 6.4 ms, max 7.3 ms; total filtrado 75

## Criacao de dados
- 50 baterias + 400 raias em 2602 ms (52.0 ms/bateria)

## Endpoints de leitura
- GET /api/events: mediana 21.2 ms, min 20.2 ms, max 22.7 ms, 200.4 KB
- GET /api/events/{id}: mediana 21.1 ms, min 19.9 ms, max 21.7 ms, 200.4 KB
- GET /api/events/{id}/provas: mediana 20.8 ms, min 18.2 ms, max 21.9 ms, 199.6 KB
- GET /api/provas/{id}: mediana 15.2 ms, min 14.9 ms, max 17.2 ms, 27.9 KB
- GET /api/provas/{id}/heats: mediana 34.2 ms, min 28.9 ms, max 35.4 ms, 27.5 KB
- GET /api/provas/{id}/classification: mediana 6.0 ms, min 5.8 ms, max 6.5 ms, 50.0 KB
- GET /api/provas/{id}/summary: mediana 8.2 ms, min 7.7 ms, max 9.8 ms, 26.6 KB

## Concorrencia (7 baterias da prova 1)
- 56 finalizacoes simultaneas: 56 aceitas, 2549 ms no total (45.5 ms/req)
- classificacao consolidada: 56 validos, 0 excluidos, provisoria=False

## Limites observados
- Teste in-process (ASGI), sem latencia de rede Wi-Fi; numeros servem para comparar regressoes, nao como garantia de producao.
- SQLite em WAL com um unico worker uvicorn: escritas sao serializadas; os locks por bateria evitam corrida no processo.
- Multiplos workers exigiriam banco com concorrencia de escrita (PostgreSQL) ou particionamento; ver docs/ADR/005.
