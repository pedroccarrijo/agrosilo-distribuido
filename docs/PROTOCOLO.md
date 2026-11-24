# Protocolo AgroSilo — Checkpoint 1

Servidor IPv4 TCP. Endereço padrão `127.0.0.1:9000`. A troca é síncrona, com uma requisição e uma resposta por conexão. Cada objeto JSON UTF-8 deve terminar com LF (byte 10), sem quebras de linha literais dentro do objeto. O limite de 16.384 bytes em cada sentido exclui o LF. Um objeto pode chegar em vários segmentos TCP. O prazo de leitura é aplicado ao quadro inteiro, independentemente do número de segmentos. O servidor fecha a conexão após a resposta.

Pedido `{"operacao":"listar_silos","dados":{}}`. O campo `dados` é opcional e, quando presente, deve ser um objeto. Resposta de sucesso `{"ok":true,"dados":{"silos":[],"proximo_apos_id":null}}`. Resposta de falha `{"ok":false,"erro":{"codigo":"DADOS_INVALIDOS","mensagem":"..."}}`.

| Operação | Campos de dados | Conteúdo da resposta de sucesso |
| --- | --- | --- |
| cadastrar_silo | `nome` de 1 a 80 caracteres após retirar espaços nas extremidades | `id`, `nome` |
| consultar_silo | `silo_id` positivo | `id`, `nome`, `ultima_medicao` (ou `null`) |
| listar_silos | `limite` opcional (1–15, padrão 15), `apos_id` opcional (padrão 0) | `silos` em ordem crescente de ID e cursor `proximo_apos_id` |
| registrar_medicao | `silo_id`, `temperatura` de −273,15 a 1000 °C, `umidade` de 0 a 100% | Medição registrada com avaliação |
| consultar_medicoes | `silo_id`, `limite` opcional (1–40, padrão 20), `antes_id` opcional | `medicoes` em ordem decrescente de ID e cursor `proximo_antes_id` |

Para continuar, envie o cursor retornado no campo de paginação correspondente. O cursor vale `null` na última página. Uma medição inclui `id`, `silo_id`, `temperatura`, `umidade`, `registrada_em` em ISO 8601 UTC, `status` (`normal` ou `alerta`), `alertas` (campos que excederam seus limites) e `limites_demonstrativos`. A avaliação usa os limites vigentes no servidor no momento da consulta. Leituras iguais ao limite ficam dentro da faixa demonstrativa.

Erros de aplicação usam `DADOS_INVALIDOS`, `OPERACAO_DESCONHECIDA`, `SILO_INEXISTENTE` ou `ERRO_INTERNO`. O servidor usa `MENSAGEM_INVALIDA` para JSON inválido, quadro grande demais ou EOF após quadro parcial, e `TIMEOUT` se o LF não chegar no prazo. EOF antes de qualquer byte fecha a sessão. O cliente trata problemas de conexão, timeout e respostas ausentes ou inválidas. A escrita concluída no SQLite pode persistir mesmo quando o cliente perde a resposta. Repetir um cadastro ou registro pode gerar outro ID.

## Extensões dos checkpoints 2 e 3

As operações e o enquadramento públicos continuam iguais. No modo replicado, uma escrita pública no secundário recebe `SOMENTE_LEITURA`. O primário retorna `REPLICA_INDISPONIVEL` se bloquear um pedido ou se uma escrita ficar pendente. A mensagem de erro distingue uma nova escrita bloqueada de uma pendência a reconciliar.

No Checkpoint 3, o cliente pode tentar a mesma consulta uma vez no secundário quando o primário apresentar erro de rede, timeout ou encerramento antes de completar a resposta. A resposta JSON válida de qualquer servidor segue o contrato público. Cada operação volta a preferir o primário. Escritas são enviadas apenas ao endereço principal.

A comunicação interna usa `_estado_replica` com `chave` para verificar a sequência aplicada, e `_replicar` com `chave`, `sequencia`, `operacao` e `registro` para aplicar o evento. As duas respostas internas bem-sucedidas têm `{"ok":true,"dados":{"sequencia":1}}`, com a sequência efetiva no lugar de 1.
