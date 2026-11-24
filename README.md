# AgroSilo — Sistema Distribuído de Monitoramento de Silos de Grãos

Checkpoint 3 da disciplina de Sistemas Distribuídos. O servidor recebe medições via TCP, registra as leituras em SQLite e retorna o histórico e alertas demonstrativos.

## Executar um servidor no Windows

Use Python 3.10 ou superior em dois terminais PowerShell abertos na raiz do projeto. Os comandos usam o launcher `py`. Se sua instalação disponibiliza `python` no PATH, substitua `py -3` por `python`. O projeto usa somente a biblioteca padrão.

Terminal 1, servidor:

```powershell
py -3 -m agrosilo.server
```

Terminal 2, cliente:

```powershell
py -3 -m agrosilo.client cadastrar_silo "Silo Norte"
py -3 -m agrosilo.client listar_silos
py -3 -m agrosilo.client registrar_medicao 1 25.5 58
py -3 -m agrosilo.client registrar_medicao 1 34 72
py -3 -m agrosilo.client simular 1
py -3 -m agrosilo.client consultar_silo 1
py -3 -m agrosilo.client consultar_medicoes 1 --limite 10
```

Use o ID retornado pelo cadastro no lugar de `1` se já houver registros. Com a configuração padrão, a primeira leitura manual fica normal e a segunda aciona os dois alertas. A simulação gera uma leitura por execução. Para demonstrar dois clientes, abra outro terminal e execute comandos enquanto o servidor segue ativo. Encerre o servidor com Ctrl+C.

O servidor usa `127.0.0.1:9000` e cria o arquivo `data/agrosilo.sqlite3`. Um exemplo com porta, caminho e limites alternativos:

```powershell
py -3 -m agrosilo.server --port 9010 --db data/demo.sqlite3 --max-temperatura 28 --max-umidade 62 --timeout 5
py -3 -m agrosilo.client --port 9010 listar_silos
```

Execute cada linha em seu terminal correspondente. Os flags globais do cliente, como `--host`, `--port` e `--timeout`, vêm antes da operação. Os limites são demonstrativos. Os comandos de cliente imprimem JSON e saem com código 0 para sucesso ou 1 para falhas de aplicação e comunicação.

## Executar a dupla replicada no Windows

Use dois terminais para os servidores. Defina a mesma chave nos dois e inicie primeiro o secundário. Para a primeira demonstração, use dois bancos novos. O modo independente descrito acima continua disponível.

No terminal do secundário:

```powershell
$env:AGROSILO_REPLICATION_KEY = 'agrosilo-demo'
py -3 -m agrosilo.server --role secondary --port 9001 --db data/secondary.sqlite3
```

No terminal do primário:

```powershell
$env:AGROSILO_REPLICATION_KEY = 'agrosilo-demo'
py -3 -m agrosilo.server --role primary --port 9000 --db data/primary.sqlite3 --replica-port 9001
```

No terminal do cliente:

```powershell
py -3 -m agrosilo.client cadastrar_silo "Silo Norte"
py -3 -m agrosilo.client registrar_medicao 1 34 72
py -3 -m agrosilo.client consultar_silo 1
py -3 -m agrosilo.client --port 9001 consultar_silo 1
```

Use o ID retornado pelo cadastro. As consultas nas duas portas devem mostrar a mesma leitura. Nos terminais dos servidores, acompanhe o envio, a persistência e a confirmação de cada sequência. Uma tentativa de cadastro na porta 9001 retorna `SOMENTE_LEITURA`.

O cliente tenta primeiro o primário. Se uma consulta falhar por timeout ou conexão, ele tenta o secundário automaticamente. Por padrão, usa o mesmo host e a porta 9001. Os flags `--replica-host` e `--replica-port` configuram outro endereço. Use `--sem-failover` para consultar apenas o servidor selecionado. O aviso de failover vai para stderr e o resultado JSON vai para stdout.

Para demonstrar a queda do primário, encerre-o com Ctrl+C. Execute `py -3 -m agrosilo.client --timeout 1 consultar_medicoes 1`. O cliente deve indicar failover e mostrar o histórico. Tente registrar outra medição para observar que a escrita fica indisponível. Reinicie o primário com a mesma porta e banco.

Para demonstrar a queda do secundário, encerre-o com Ctrl+C. As consultas no primário seguem funcionando. Um novo cadastro retorna `REPLICA_INDISPONIVEL` sem gravar a linha. Reinicie o secundário com a mesma porta e banco para restabelecer as escritas. Se a conexão cair no meio de uma escrita, consulte o estado após a recuperação antes de reenviar o pedido.

Para levar dados do modo independente para a dupla, encerre o servidor independente e faça duas cópias consistentes do mesmo SQLite usando a `sqlite3.Connection.backup()`, uma em cada caminho da dupla, antes de iniciar qualquer nó replicado. Use os dois arquivos como par e configure os mesmos limites demonstrativos em ambos. Os servidores recusam um banco já associado a outro papel.

Para atualizar uma dupla do Checkpoint 2, pare os dois processos e reinicie ambos com o código do Checkpoint 3 e os mesmos bancos. Uma pendência do primário permanece no diário e é reconciliada na próxima requisição válida.

## Testes

```powershell
py -3 -m unittest discover -s tests -v
```

A suíte usa portas locais atribuídas pelo sistema e bancos temporários. Ela inicia seus próprios processos de servidor.

## Documentação

- [Planejamento dos três checkpoints](PLANEJAMENTO.md)
- [Relatório do Checkpoint 1](docs/RELATORIO_CHECKPOINT_1.md)
- [Contrato do protocolo TCP](docs/PROTOCOLO.md)
- [Relatório do Checkpoint 2](docs/RELATORIO_CHECKPOINT_2.md)
- [Relatório final](docs/RELATORIO_FINAL.md)
- [Roteiro para a apresentação de até 10 minutos](docs/ROTEIRO_APRESENTACAO.md)
