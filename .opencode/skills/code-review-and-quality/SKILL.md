---
name: code-review-and-quality
description: Analisa código em busca de bugs ocultos, falhas de lógica, problemas de concorrência e sugere melhorias de arquitetura, segurança e Clean Code.
metadata:
  opencode/slash: "true"
---
# Instruções de Revisão

## 1. Análise de Bugs e Lógica
- Identifique condições de corrida, loops infinitos ou vazamentos de memória.
- Verifique o tratamento de exceções (try/catch) e retornos nulos (null pointers).
- Analise se a lógica de negócios atende a casos extremos (edge cases).

## 2. Qualidade e Refatoração
- Sugira melhorias com base nos princípios SOLID e Clean Code.
- Aponte trechos de código duplicados ou funções excessivamente longas.
- Verifique a legibilidade, nomenclatura de variáveis e tipagem.

## 3. Segurança e Performance
- Identifique vulnerabilidades óbvias (injeções, falta de sanitização).
- Sugira estruturas de dados ou algoritmos mais eficientes se houver gargalos.
