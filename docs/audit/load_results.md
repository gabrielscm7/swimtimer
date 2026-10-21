# Resultado do teste de carga — SwimTimer

- Data: 2026-10-21 04:19:44
- Python: 3.11.16
- Plataforma: Linux-7.2.11-1-cachyos-x86_64-with-glibc2.44
- SQLite: 3.53.1
- Massa: 5 provas x 4 baterias x 8 raias = 160 raias; 20 equipes; 200 atletas importados

## Importacao de atletas
- 200 atletas e 0 equipes em 21 ms (0.10 ms/atleta), 0 erros
- listagem paginada: mediana 7.1 ms, max 7.7 ms; total filtrado 100

## Criacao de dados
- 20 baterias + 160 raias em 968 ms (48.4 ms/bateria)

## Endpoints de leitura
- GET /api/events: mediana 15.8 ms, min 14.1 ms, max 16.6 ms, 76.2 KB
- GET /api/events/{id}: mediana 14.4 ms, min 13.5 ms, max 15.6 ms, 76.2 KB
- GET /api/events/{id}/provas: mediana 12.5 ms, min 10.7 ms, max 13.3 ms, 73.4 KB
- GET /api/provas/{id}: mediana 10.5 ms, min 10.2 ms, max 11.5 ms, 14.7 KB
- GET /api/provas/{id}/heats: mediana 17.5 ms, min 16.3 ms, max 19.2 ms, 14.3 KB
- GET /api/provas/{id}/classification: mediana 7.5 ms, min 7.1 ms, max 8.8 ms, 27.8 KB

## Concorrencia (4 baterias da prova 1)
- 32 finalizacoes simultaneas: 32 aceitas, 804 ms no total (25.1 ms/req)
- classificacao consolidada: 32 validos, 0 excluidos, provisoria=False

## Limites observados
- Teste in-process (ASGI), sem latencia de rede Wi-Fi; numeros servem para comparar regressoes, nao como garantia de producao.
- SQLite em WAL com um unico worker uvicorn: escritas sao serializadas; os locks por bateria evitam corrida no processo.
- Multiplos workers exigiriam banco com concorrencia de escrita (PostgreSQL) ou particionamento; ver docs/ADR/005.
