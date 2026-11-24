# AgroSilo — planejamento

Sistema distribuído de monitoramento de silos de grãos. O grupo pode ter até três integrantes. O trabalho vale 60% da nota final da disciplina (0,4 × P1 + 0,6 × Trabalho). A entrega é pelo mesmo repositório Git ou por pasta compactada, conforme combinado em aula. A participação individual vale 10% do trabalho, apurada por autoavaliação e observação em aula.

As datas abaixo são as indicadas nos enunciados. O briefing prevê feedback escrito entre etapas, e os documentos orientam consultar o professor com antecedência em caso de imprevisto. Cada versão funcional terá um commit e uma tag próprios no mesmo repositório. A implementação do Checkpoint 2 começa após a validação do Checkpoint 1.

## Escopo e arquitetura

O cliente cadastra e consulta silos, registra temperatura em °C e umidade em %, e consulta a última leitura e o histórico. Um comando gera medições simuladas e as envia pelo mesmo protocolo. Os limites superiores são configurados no servidor e explicitamente demonstrativos. Cada servidor roda em processo próprio com SQLite local. Cliente e servidores usam Python 3, TCP nativo, JSON UTF-8 delimitado por quebra de linha e threads para conexões simultâneas. Os testes usam unittest.

No Checkpoint 1, o cliente conversa com um único servidor na porta padrão 9000. No Checkpoint 2, o servidor nessa porta se torna primário e envia operações ao secundário por TCP, em outra porta (proposta 9001). No Checkpoint 3, o cliente passa a consultar o secundário quando detectar indisponibilidade do primário.

| Caminho | Responsabilidade |
| --- | --- |
| agrosilo/server.py | Interface de rede, threads, configuração e logs |
| agrosilo/client.py | Cliente de terminal, simulação e função reutilizável de comunicação |
| agrosilo/protocol.py | Delimitação, serialização e leitura TCP |
| agrosilo/replication.py | Papéis, ordenação, confirmação e reenvio de eventos |
| agrosilo/service.py e agrosilo/storage.py | Validação, operações de domínio, alertas e persistência |
| tests/ | Testes automatizados com processos e bancos temporários |
| docs/ | Relatório de cada etapa e protocolo |
| data/ | Bancos SQLite gerados em execução e ignorados pelo Git |
| PDFs na raiz | Enunciados do professor usados como referência |

## Checkpoint 1 — comunicação cliente-servidor

**Prazo do enunciado:** 08/09. **Peso:** 25% do trabalho. **Rubrica:** funcionalidade 40%, organização 20%, clareza do relatório 20%, uso de comunicação nativa 20%.

Critérios de conclusão:

- Executar cliente e servidor em processos separados, com pedidos e respostas síncronos por TCP.
- Demonstrar cadastro, consulta, listagem, registro, histórico, alertas e sensor simulado. Confirmar persistência após reinício.
- Testar dois clientes conectados simultaneamente, mensagens inválidas, timeout e desconexão.
- Entregar o código, as instruções para Windows e um relatório de cerca de uma página com processos, portas, arquitetura e protocolo.

## Checkpoint 2 — replicação e consistência

**Prazo do enunciado:** 29/10. **Peso:** 30% do trabalho. **Rubrica:** replicação 40%, consistência 25%, evolução 20%, clareza 15%.

Critérios de conclusão:

- Executar primário e secundário em processos e portas distintos, cada um com seu próprio arquivo SQLite.
- Centralizar e ordenar as escritas no primário. Replicar as operações com os mesmos identificadores e dados por TCP. Responder sucesso somente após persistência nos dois bancos e confirmação da réplica.
- Demonstrar a replicação com logs e consultas aos dois bancos. Testar escritas concorrentes e validar o cliente da versão anterior com a porta e o protocolo originais.
- Registrar no relatório o antes e depois, a razão da escolha primária-secundária e os limites de consistência. Uma confirmação perdida pode deixar o resultado indeterminado para o cliente. Cobrir falhas antes e após a gravação remota, interrupção entre commits locais e reconciliação de operações pendentes. Definir o tratamento de reenvios e o custo de disponibilidade e latência da confirmação síncrona.

## Checkpoint 3 — tolerância a falhas e entrega final

**Prazo do enunciado:** 15/12. **Peso:** 35% do trabalho. **Rubrica:** tolerância a falhas 35%, relatório 25%, apresentação 25%, integração 15%.

Critérios de conclusão:

- Detectar falha por timeout ou erro de conexão e encaminhar automaticamente as consultas ao secundário. Manter o secundário em modo de leitura.
- Bloquear escritas quando faltar confirmação da réplica e durante recuperação até que o estado esteja reconciliado. A aplicação deve continuar oferecendo consultas em modo degradado quando um servidor cair, sem reiniciar todos os processos.
- Testar queda do primário, queda do secundário, perda de confirmação e retomada com os dois bancos disponíveis. Demonstrar a degradação e recuperação com processos separados.
- Entregar código consolidado e relatório final com histórico real da evolução, arquitetura, decisões e evidências dos testes. Preparar e ensaiar uma apresentação de até 10 minutos na Aula 31, com demonstração de falha e recuperação e participação dos integrantes.

## Evolução posterior

Uma interface web poderá apresentar temperatura, umidade, status de silos, disponibilidade dos servidores e eventos de replicação. A aplicação web servirá como cliente intermediário via TCP e os servidores manterão suas interfaces de rede e bancos locais.
