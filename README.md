# AgroSilo — Sistema Distribuído de Monitoramento de Silos de Grãos

Checkpoint 2 da disciplina de Sistemas Distribuídos. O servidor recebe medições via TCP, registra as leituras em SQLite e retorna o histórico e alertas demonstrativos.

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

Para demonstrar a perda de disponibilidade de escrita, encerre o secundário com Ctrl+C e tente cadastrar outro silo no primário. O cliente recebe `REPLICA_INDISPONIVEL`. Reinicie o secundário com o mesmo comando e consulte `listar_silos` no primário. Essa consulta dispara a reconciliação do evento pendente. Um cadastro pendente pode aparecer após ela, mesmo que o cliente tenha recebido erro na tentativa original.

Para levar dados do modo independente para a dupla, encerre o servidor independente e faça duas cópias consistentes do mesmo SQLite usando a `sqlite3.Connection.backup()`, uma em cada caminho da dupla, antes de iniciar qualquer nó replicado. Use os dois arquivos como par e configure os mesmos limites demonstrativos em ambos. Os servidores recusam um banco já associado a outro papel.

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
