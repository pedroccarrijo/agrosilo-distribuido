# AgroSilo — Relatório do Checkpoint 2

## Evolução da arquitetura

No Checkpoint 1, o cliente enviava requisições síncronas por TCP a um servidor. A confirmação de escrita dependia de um único commit SQLite. Nesta etapa, o mesmo cliente pode se conectar ao primário na porta 9000 com as mesmas operações e o mesmo formato de resposta. O secundário roda em outro processo, na porta 9001, com um arquivo SQLite próprio. Ambos podem responder a consultas. As escritas de clientes entram pelo primário, que decide a ordem e gera IDs e horários UTC. As duas instâncias usam as mesmas configurações de alerta para que a avaliação seja equivalente.

O primário serializa as requisições com uma trava no processo. Uma transação local grava o dado de domínio e o evento pendente na tabela `replicacao`. Em seguida, o primário envia o evento por TCP. O secundário valida a sequência, grava o dado com os IDs e valores recebidos e atualiza seu marcador na mesma transação. Após o commit, o secundário responde com a sequência aplicada. O primário limpa a pendência local e só então responde sucesso ao cliente. Os logs indicam a sequência enviada, persistida, reconfirmada ou confirmada no primário.

A replicação primária-secundária síncrona atende ao requisito de conservar as escritas bem-sucedidas nos dois bancos. Centralizar a ordem em um único primário evita que duas instâncias aceitem alterações concorrentes sobre estados independentes. O custo é o percurso adicional de rede e de persistência, além da perda de disponibilidade de escrita quando a réplica não consegue confirmar.

## Garantias e limites

- Uma escrita confirmada ao cliente foi persistida nos dois SQLite. As escritas passam por uma única ordem, com até um evento pendente por vez.
- Se a transmissão falhar antes da gravação no secundário, o primário mantém a alteração e o evento pendentes no mesmo banco. As próximas operações válidas no primário tentam reconciliá-lo antes de prosseguir. Se a réplica continuar indisponível, a operação recebe `REPLICA_INDISPONIVEL`. As consultas diretas ao secundário continuam disponíveis no estado aplicado até então.
- Se apenas a confirmação do secundário se perder, o evento pode estar nos dois bancos. Ao receber novamente a última sequência com conteúdo idêntico, o secundário confirma o evento existente. Um evento com sequência inesperada ou conteúdo divergente é recusado.
- Se o primário cair após o commit local ou antes de limpar a pendência, a próxima requisição válida após o reinício tentará o mesmo reenvio. Se o cliente perder a resposta final, deve consultar o estado antes de reenviar uma escrita. Reenvios de eventos de replicação são idempotentes. Novos pedidos do cliente continuam sujeitos à criação de outro ID.
- A confirmação síncrona dá consistência às escritas confirmadas. A aplicação em dois bancos tem uma janela intermediária. Durante uma falha ou antes da resposta final, clientes podem observar no secundário um evento cujo resultado ainda é incerto para o solicitante. Por isso, o sistema oferece confirmação durável nos dois nós, sem promessa de commit atômico distribuído ou de leitura linearizável em ambas as portas em todos os cenários.
- A configuração tem um primário, um secundário e uma cópia inicial comum. A perda ou substituição de um banco requer restauração coordenada. A sequência é um controle de ordem, e o secundário retém somente o último evento para reconfirmar. O Checkpoint 2 exige seleção manual da porta para consultar o secundário. A recuperação da pendência ocorre sob demanda.

## Protocolo interno

A operação `_replicar` usa o mesmo enquadramento JSON por linha do [protocolo público](PROTOCOLO.md). O pedido contém `chave`, `sequencia`, `operacao` e `registro`. O secundário devolve `{"ok":true,"dados":{"sequencia":1}}` após persistir ou confirmar uma repetição idêntica. A chave compartilhada vem de `AGROSILO_REPLICATION_KEY`, é usada apenas na operação interna e trafega em texto simples. A demonstração usa loopback. Escritas públicas enviadas ao secundário recebem `SOMENTE_LEITURA`.

## Validação

Os testes de integração executam dois subprocessos e comparam os bancos SQLite. Eles cobrem cadastro e medição com IDs e horários iguais, recusa de escritas públicas no secundário, ordem sob concorrência, indisponibilidade da réplica, recuperação de pendência após reinício e perda de ACK após commit remoto. A compatibilidade do cliente original também é verificada usando os arquivos extraídos da tag `checkpoint-1`.

Em 24/11/2026, os 12 testes da suíte passaram no Windows com Python 3.12.14. O teste adicional com o cliente da tag anterior confirmou o registro e a consulta de uma medição replicada após migrar um silo preexistente para dois bancos via backup SQLite.
