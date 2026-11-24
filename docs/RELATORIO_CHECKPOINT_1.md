# AgroSilo — Relatório do Checkpoint 1

O AgroSilo monitora silos de grãos. O cliente de terminal cadastra silos, lista os cadastrados, registra dados de sensores simulados e consulta a última leitura e o histórico. O servidor armazena as medições com data e hora em UTC. Quando temperatura ou umidade excede seu limite superior configurável, a resposta identifica o campo e marca a leitura como alerta. Os limites padrão de 30 °C e 65% são demonstrativos.

## Arquitetura

Há um processo servidor e um processo cliente por comando. Por padrão, a comunicação usa TCP em `127.0.0.1:9000`. O servidor aceita conexões simultâneas e atende cada uma em uma thread, com uma conexão SQLite própria por requisição. O banco fica no servidor, no arquivo `data/agrosilo.sqlite3`. O servidor confirma a escrita após o commit local. O cliente aguarda a resposta de forma síncrona.

## Protocolo

Cada conexão transporta uma requisição e uma resposta. Ambas são objetos JSON codificados em UTF-8, com até 16.384 bytes antes do delimitador LF (`\n`). O servidor acumula os bytes até o delimitador, processa a operação, envia a resposta e fecha a conexão.

```json
{"operacao":"cadastrar_silo","dados":{"nome":"Silo Norte"}}
{"ok":true,"dados":{"id":1,"nome":"Silo Norte"}}
{"ok":false,"erro":{"codigo":"SILO_INEXISTENTE","mensagem":"Silo não encontrado."}}
```

As operações são `cadastrar_silo`, `consultar_silo`, `listar_silos`, `registrar_medicao` e `consultar_medicoes`. O cliente simula o sensor enviando `registrar_medicao` com valores gerados localmente. O [contrato do protocolo](PROTOCOLO.md) descreve argumentos, paginação e erros.

O prazo padrão é de cinco segundos para receber a mensagem completa. O servidor responde com um erro estruturado a quadros inválidos e a timeouts, quando ainda consegue escrever no socket. O cliente exibe um erro de comunicação se o servidor estiver indisponível ou encerrar a conexão antes de responder. Se a resposta a uma escrita for perdida após a gravação, o cliente deve consultar o estado para verificar o resultado.

## Validação

A suíte de integração inicia o servidor em um subprocesso com banco temporário. Ela verifica o cliente de terminal e o sensor simulado, conexões simultâneas, escritas concorrentes, histórico paginado, limites demonstrativos, persistência após reinício, mensagens inválidas, desconexão, timeout e conexão recusada.

Em 24/11/2026, os oito testes passaram no Windows com Python 3.12.14.
