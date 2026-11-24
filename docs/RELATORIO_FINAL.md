# AgroSilo — Relatório final

- **Disciplina** — Sistemas Distribuídos
- **Professor** — Leandro Borges
- **Projeto** — Sistema Distribuído de Monitoramento de Silos de Grãos

## Problema e escopo

O AgroSilo registra silos, temperatura em °C e umidade em %. O cliente consulta a última leitura e o histórico paginado. Um comando simula um sensor gerando valores e os envia pelo mesmo protocolo utilizado no registro manual. O servidor calcula alertas com limites superiores configuráveis. Os padrões de 30 °C e 65% são demonstrativos.

## Evolução do projeto

| Etapa | Decisão e resultado |
| --- | --- |
| Checkpoint 1 · `checkpoint-1` · `354a017` | Cliente de terminal e servidor separados. TCP explícito com JSON por linha. Threads atendem clientes simultâneos e SQLite preserva os dados após reinício. |
| Checkpoint 2 · `checkpoint-2` · `01f0e16` | Dois servidores em portas diferentes, com SQLite próprios. Um primário ordena as escritas. A resposta de sucesso depende da confirmação do secundário. Um evento durável pode ser reenviado após perda de confirmação. O cliente original continua compatível. |
| Checkpoint 3 · `checkpoint-3` | O cliente encaminha consultas ao secundário quando detecta falha de comunicação. O primário verifica a réplica antes de preparar uma escrita e publica localmente a linha após a confirmação remota. Eventos pendentes ficam no diário até a reconciliação. |

## Arquitetura final

O modo replicado inicia um servidor primário em `127.0.0.1:9000` e um secundário em `127.0.0.1:9001`. Cada processo acessa seu próprio arquivo SQLite. O cliente envia um objeto JSON UTF-8 terminado por LF, aguarda uma resposta e fecha a conexão. Os servidores usam uma thread por conexão. O primário mantém uma trava para preservar a ordem das escritas e da recuperação. O secundário aceita consultas públicas e aplica escritas recebidas pelo canal interno de replicação com chave compartilhada.

Uma escrita segue este fluxo:

1. O primário verifica se o secundário responde e informa a mesma sequência. Se houver pendência anterior, tenta reconciliá-la antes de consultar a sequência para uma nova escrita.
2. O primário prepara a operação no SQLite usando um ponto de salvamento para reutilizar a validação e gerar ID e horário. Ele desfaz a inserção temporária e grava o evento completo e a sequência no diário na mesma transação.
3. O secundário aplica a próxima sequência em uma transação local e responde após o commit. O reenvio da última sequência, com conteúdo idêntico, recebe a mesma confirmação sem inserir outra linha.
4. O primário grava a linha definitiva, limpa a pendência na mesma transação e então responde sucesso. O dado confirmado existe nos dois arquivos.

## Falhas e degradação controlada

| Situação | Comportamento |
| --- | --- |
| Primário indisponível | Timeout, erro de conexão ou encerramento prematuro detectado durante consulta dispara uma tentativa no secundário. A próxima consulta volta a tentar o primário primeiro. |
| Secundário indisponível | O primário segue servindo consultas a partir do seu banco. A verificação da réplica bloqueia uma nova escrita sem publicar uma linha ou avançar a sequência. |
| Conexão cai após a preparação | O primário mantém um único evento pendente e impede nova escrita até reconciliá-lo. Se a reconciliação falhar, as consultas no primário retornam seu estado confirmado. |
| Secundário grava e o ACK se perde | A escrita pode aparecer em consulta ao secundário. O primário repete o evento e recebe uma reconfirmação idempotente. Depois disso aplica a alteração local e libera novas escritas. |
| Os dois processos indisponíveis | O cliente informa as falhas dos dois endereços nas consultas. |
| Primário ou secundário retorna | O operador reinicia somente o processo afetado, com a mesma porta e o mesmo banco. As consultas voltam a preferir o primário e a próxima requisição válida tenta reconciliar eventual pendência. |

Os papéis permanecem fixos durante as falhas. Escritas, inclusive a simulação de sensor, são enviadas apenas ao primário. O cliente não repete uma escrita com resultado incerto. Uma consulta após recuperação permite verificar se o registro foi aplicado antes de repetir o pedido. Respostas válidas de erro de domínio, como `SILO_INEXISTENTE`, são devolvidas diretamente ao cliente.

O projeto prioriza a consistência das escritas confirmadas. A verificação e a confirmação exigem comunicação com os dois nós, elevando a latência e reduzindo a disponibilidade de escrita durante falhas. Os commits são locais e existe uma janela entre eles. O secundário pode mostrar um evento que ainda está pendente no primário. A solução oferece persistência em ambos os nós para escritas confirmadas, com uma possível diferença temporária durante a recuperação. Duas cópias com a mesma origem e a mesma configuração de alertas fazem parte da configuração operacional. A perda de um arquivo SQLite requer recuperação coordenada dos bancos.

## Validação

Execute `py -3 -m unittest discover -s tests -v` na raiz. A suíte usa processos reais, portas TCP locais e bancos descartáveis.

| Cenário exercitado | Evidência verificada |
| --- | --- |
| Comunicação e domínio | Cliente CLI, sensor simulado, alertas, histórico, paginação, concorrência, persistência após reinício e erros de protocolo. |
| Replicação | Linhas com os mesmos IDs, horários e valores nos dois arquivos. Escritas concorrentes seguem uma sequência única. O secundário recusa escritas públicas. |
| Queda e retorno do primário | Consulta CLI pelo secundário, registro bloqueado durante falha e nova gravação replicada após reinício na mesma porta. |
| Queda e retorno do secundário | Consulta no primário, escrita recusada sem alteração local e réplica voltando a receber novos eventos após reinício. |
| Timeout e indisponibilidade total | Um listener silencioso aciona failover. Quando ambos os endereços falham, a CLI identifica os dois. |
| Interrupção durante replicação | O evento fica durável. A recuperação preserva o ID e reconcilia a alteração mesmo quando a confirmação remota se perde. |

Em 24/11/2026, os 17 testes automatizados passaram no Windows com Python 3.12.14. A validação adicional iniciou o sistema nas portas 9000 e 9001, reconciliou um evento pendente criado com o código da tag do Checkpoint 2, confirmou uma consulta com o cliente original do Checkpoint 1 e verificou o failover com a configuração padrão.

O [README](../README.md) descreve a execução no Windows. O [roteiro de apresentação](ROTEIRO_APRESENTACAO.md) organiza a demonstração ao vivo da falha e da recuperação.
