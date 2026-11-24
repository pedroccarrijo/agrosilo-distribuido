# AgroSilo — Sistema Distribuído de Monitoramento de Silos de Grãos

Checkpoint 1 da disciplina de Sistemas Distribuídos. O servidor recebe medições via TCP, registra as leituras em SQLite e retorna o histórico e alertas demonstrativos.

## Executar no Windows

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

## Testes

```powershell
py -3 -m unittest discover -s tests -v
```

A suíte usa portas locais atribuídas pelo sistema e bancos temporários. Ela inicia seus próprios processos de servidor.

## Documentação

- [Planejamento dos três checkpoints](PLANEJAMENTO.md)
- [Relatório do Checkpoint 1](docs/RELATORIO_CHECKPOINT_1.md)
- [Contrato do protocolo TCP](docs/PROTOCOLO.md)
