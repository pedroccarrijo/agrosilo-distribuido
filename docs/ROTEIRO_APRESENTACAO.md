# AgroSilo — Roteiro para a Aula 31

Use três terminais PowerShell, um para cada servidor e um para o cliente. Inicie os servidores conforme o [README](../README.md), com dois bancos novos para a demonstração. Em bancos novos, o primeiro silo recebe ID `1`. Se já existir um banco de demonstração, use o ID que aparecer no cadastro.

| Tempo | Quem conduz | Demonstração e ponto a explicar |
| --- | --- | --- |
| 0:00–1:00 | Integrante 1 | Apresente o domínio, as leituras em °C e % e o caráter demonstrativo dos alertas. |
| 1:00–3:00 | Integrante 1 | Cadastre um silo. Explique os processos, as portas, o TCP e o delimitador LF do JSON. |
| 3:00–5:00 | Integrante 2 | Registre uma medição alta. Consulte o mesmo silo nos dois servidores e mostre os logs de sequência, persistência e confirmação. |
| 5:00–7:00 | Integrante 3 | Interrompa o primário, mostre o failover da consulta e tente uma escrita. Reinicie o primário com o mesmo comando e banco. |
| 7:00–9:00 | Integrante 3 | Interrompa o secundário. Mostre que o primário segue consultável, mas recusa escritas. Reinicie o secundário e mostre uma nova medição nos dois nós. |
| 9:00–10:00 | Grupo | Explique a perda de confirmação, a recuperação sem duplicidade e o custo da replicação síncrona. Reserve o tempo restante para perguntas. |

Em grupo menor, reúna blocos adjacentes. Cada integrante deve conseguir explicar a comunicação, a replicação e o comportamento durante falhas.

## Comandos no terminal do cliente

Na operação normal, confirme o cadastro, a mesma leitura nas duas portas e os eventos nos logs dos servidores.

```powershell
py -3 -m agrosilo.client cadastrar_silo "Silo Norte"
py -3 -m agrosilo.client registrar_medicao 1 34 72
py -3 -m agrosilo.client consultar_silo 1
py -3 -m agrosilo.client --port 9001 consultar_silo 1
```

Com o primário interrompido por Ctrl+C, a consulta exibe `Failover de leitura` e retorna o histórico. A tentativa de escrita informa falta de confirmação.

```powershell
py -3 -m agrosilo.client --timeout 1 consultar_medicoes 1
py -3 -m agrosilo.client --timeout 1 registrar_medicao 1 25 58
```

Reinicie o primário. Em seguida, interrompa o secundário por Ctrl+C. O primário ainda lista os silos. O registro retorna `REPLICA_INDISPONIVEL`.

```powershell
py -3 -m agrosilo.client listar_silos
py -3 -m agrosilo.client registrar_medicao 1 25 58
```

Reinicie somente o secundário. Depois, use os comandos abaixo para mostrar a retomada e o histórico replicado.

```powershell
py -3 -m agrosilo.client registrar_medicao 1 26 57
py -3 -m agrosilo.client consultar_medicoes 1
py -3 -m agrosilo.client --port 9001 consultar_medicoes 1
```

## Pontos para as perguntas

- Uma escrita bem-sucedida existe nos dois bancos. Se a resposta se perder durante a operação, o cliente consulta o estado antes de decidir sobre novo envio.
- O secundário conserva o último evento para confirmar reenvio idêntico. Esse reenvio usa a mesma sequência e o mesmo ID.
- O mecanismo de falha mantém a disponibilidade de leitura quando há um servidor alcançável e preserva a regra de confirmação nos dois bancos para escritas.
