import json
import os
import queue
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from agrosilo.client import request
from agrosilo.protocol import receive_message, send_message

HOST = "127.0.0.1"
KEY = "chave-integracao"


class ReplicatedSystemTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.primary_db = self.root / "primary.sqlite3"
        self.secondary_db = self.root / "secondary.sqlite3"

    def start(self, role, db, replica_port=9001, port=0):
        process = subprocess.Popen(
            [sys.executable, "-m", "agrosilo.server", "--role", role, "--port", str(port),
             "--db", str(db), "--replica-port", str(replica_port)],
            env={**os.environ, "AGROSILO_REPLICATION_KEY": KEY},
            stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop, process)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        line = ready.get(timeout=10)
        self.assertIn("ouvindo", line)
        return process, int(line.rsplit(":", 1)[1])

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()

    @staticmethod
    def state(path):
        with closing(sqlite3.connect(path)) as db:
            return (
                db.execute("SELECT * FROM silos ORDER BY id").fetchall(),
                db.execute("SELECT * FROM medicoes ORDER BY id").fetchall(),
                db.execute("SELECT sequencia, evento FROM replicacao").fetchone(),
            )

    def success(self, port, operation, **data):
        response = request(HOST, port, operation, data)
        self.assertTrue(response["ok"], response)
        return response["dados"]

    def failure(self, code, port, operation, **data):
        response = request(HOST, port, operation, data)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["erro"]["codigo"], code)

    def test_replicates_silos_and_measurements_with_the_same_ids_and_timestamps(self):
        _, secondary = self.start("secondary", self.secondary_db)
        _, primary = self.start("primary", self.primary_db, secondary)

        self.failure("SOMENTE_LEITURA", secondary, "cadastrar_silo", nome="Não gravar")
        self.failure("SOMENTE_LEITURA", secondary, "registrar_medicao",
                     silo_id=1, temperatura=25, umidade=55)
        self.failure("REPLICACAO_NEGADA", secondary, "_replicar", chave="incorreta")
        silo = self.success(primary, "cadastrar_silo", nome="Soja")
        measurement = self.success(primary, "registrar_medicao", silo_id=silo["id"],
                                   temperatura=31.5, umidade=75)
        self.assertEqual(self.success(secondary, "consultar_silo", silo_id=silo["id"]),
                         {**silo, "ultima_medicao": measurement})
        first = self.state(self.primary_db)
        second = self.state(self.secondary_db)
        self.assertEqual(first[:2], second[:2])
        self.assertEqual(first[2], (2, None))
        self.assertEqual(second[2][0], 2)
        self.failure("SEQUENCIA_INVALIDA", secondary, "_replicar", chave=KEY, sequencia=2,
                     operacao="cadastrar_silo", registro={"id": 42, "nome": "Divergente"})

    def test_concurrent_writes_keep_one_order(self):
        _, secondary = self.start("secondary", self.secondary_db)
        _, primary = self.start("primary", self.primary_db, secondary)
        barrier = threading.Barrier(5, timeout=5)

        def write(index):
            barrier.wait()
            return self.success(primary, "cadastrar_silo", nome=f"Silo {index}")["id"]

        with ThreadPoolExecutor(max_workers=5) as clients:
            self.assertEqual(sorted(clients.map(write, range(5))), list(range(1, 6)))
        first = self.state(self.primary_db)
        second = self.state(self.secondary_db)
        self.assertEqual(first[:2], second[:2])
        self.assertEqual(first[2], (5, None))
        self.assertEqual(second[2][0], 5)

    def cli(self, primary, secondary, *args, timeout=5):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "agrosilo.client",
             "--port", str(primary), "--replica-port", str(secondary),
             "--timeout", str(timeout), *args],
            capture_output=True, encoding="utf-8", timeout=15,
        )

    def test_primary_stops_reads_fail_over_and_writes_resume_after_restart(self):
        _, secondary = self.start("secondary", self.secondary_db)
        primary_process, primary = self.start("primary", self.primary_db, secondary)
        self.success(primary, "cadastrar_silo", nome="Soja")
        self.success(primary, "registrar_medicao", silo_id=1, temperatura=25, umidade=50)
        self.stop(primary_process)

        read = self.cli(primary, secondary, "consultar_medicoes", "1", timeout=1)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertIn(f"Failover de leitura para {HOST}:{secondary}", read.stderr)
        self.assertEqual(len(json.loads(read.stdout)["dados"]["medicoes"]), 1)

        write = self.cli(primary, secondary, "simular", "1", timeout=1)
        self.assertEqual(write.returncode, 1)
        self.assertIn("Escrita sem confirmação", write.stderr)
        self.assertEqual(write.stdout, "")
        self.assertEqual(len(self.state(self.secondary_db)[1]), 1)

        self.start("primary", self.primary_db, secondary, port=primary)
        recovered = self.cli(primary, secondary, "listar_silos")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(recovered.stderr, "")
        self.success(primary, "registrar_medicao", silo_id=1, temperatura=27, umidade=55)
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])

    def test_secondary_stops_primary_reads_keep_working_writes_are_blocked(self):
        secondary_process, secondary = self.start("secondary", self.secondary_db)
        _, primary = self.start("primary", self.primary_db, secondary)
        silo = self.success(primary, "cadastrar_silo", nome="Milho")
        self.stop(secondary_process)

        self.assertEqual(self.success(primary, "listar_silos")["silos"], [silo])
        self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Bloqueado")
        self.assertEqual(self.state(self.primary_db)[0], [(1, "Milho")])
        self.assertEqual(self.state(self.primary_db)[2], (1, None))

        self.start("secondary", self.secondary_db, port=secondary)
        self.assertEqual(self.success(primary, "cadastrar_silo", nome="Trigo")["id"], 2)
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])

    def test_read_timeout_fails_over_but_valid_application_error_stays_on_primary(self):
        _, secondary = self.start("secondary", self.secondary_db)
        _, primary = self.start("primary", self.primary_db, secondary)
        missing = self.cli(primary, secondary, "consultar_silo", "123")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stderr, "")
        self.assertEqual(json.loads(missing.stdout)["erro"]["codigo"], "SILO_INEXISTENTE")
        with socket.socket() as silent:
            silent.bind((HOST, 0))
            silent.listen()
            result = self.cli(silent.getsockname()[1], secondary, "listar_silos", timeout=0.3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Failover de leitura", result.stderr)

    def test_both_unavailable_report_both_addresses(self):
        with socket.socket() as first, socket.socket() as second:
            for listener in (first, second):
                listener.bind((HOST, 0))
            ports = [listener.getsockname()[1] for listener in (first, second)]
            result = self.cli(*ports, "listar_silos", timeout=0.2)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"Primário {HOST}:{ports[0]}", result.stderr)
        self.assertIn(f"Secundário {HOST}:{ports[1]}", result.stderr)

    def test_pending_event_before_remote_commit_is_applied_after_restart(self):
        _, secondary = self.start("secondary", self.secondary_db)

        def interrupt_before_apply(listener):
            conn, _ = listener.accept()
            with conn:
                check = receive_message(conn, 3)
                self.assertEqual(check["operacao"], "_estado_replica")
                send_message(conn, request(HOST, secondary, check["operacao"], check["dados"]), 3)
            conn, _ = listener.accept()
            with conn:
                self.assertEqual(receive_message(conn, 3)["operacao"], "_replicar")

        with socket.socket() as proxy, ThreadPoolExecutor(max_workers=1) as worker:
            proxy.bind((HOST, 0))
            proxy.listen()
            proxy.settimeout(10)
            result = worker.submit(interrupt_before_apply, proxy)
            process, primary = self.start("primary", self.primary_db, proxy.getsockname()[1])
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Arroz")
            result.result(timeout=5)
            self.stop(process)

        self.assertEqual(self.state(self.primary_db)[0], [])
        self.assertEqual(self.state(self.secondary_db)[0], [])
        self.assertIsNotNone(self.state(self.primary_db)[2][1])
        _, primary = self.start("primary", self.primary_db, secondary)
        self.assertEqual(self.success(primary, "listar_silos")["silos"],
                         [{"id": 1, "nome": "Arroz"}])
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])

    def test_unexpected_replica_sequence_blocks_write_before_preparing(self):
        _, secondary = self.start("secondary", self.secondary_db)
        _, primary = self.start("primary", self.primary_db, secondary)
        self.success(primary, "cadastrar_silo", nome="Milho")
        self.success(secondary, "_replicar", chave=KEY, sequencia=2,
                     operacao="cadastrar_silo", registro={"id": 2, "nome": "Outro evento"})
        self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Bloqueado")
        self.assertEqual(self.state(self.primary_db)[0], [(1, "Milho")])
        self.assertEqual(self.state(self.primary_db)[2], (1, None))


    def test_applied_event_with_lost_ack_is_replayed_without_duplicate(self):
        _, secondary = self.start("secondary", self.secondary_db)

        def lose_ack(listener):
            for expected in ("_estado_replica", "_replicar", "_replicar", "_replicar"):
                conn, _ = listener.accept()
                with conn:
                    message = receive_message(conn, 3)
                    self.assertEqual(message["operacao"], expected)
                    if expected == "_estado_replica":
                        response = request(HOST, secondary, expected, message["dados"])
                        send_message(conn, response, 3)
                    else:
                        self.assertEqual(self.success(secondary, expected, **message["dados"]),
                                         {"sequencia": 1})

        with socket.socket() as proxy, ThreadPoolExecutor(max_workers=1) as worker:
            proxy.bind((HOST, 0))
            proxy.listen()
            proxy.settimeout(10)
            result = worker.submit(lose_ack, proxy)
            process, primary = self.start("primary", self.primary_db, proxy.getsockname()[1])
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Milho")
            self.assertEqual(self.success(primary, "listar_silos")["silos"], [])
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Bloqueado")
            result.result(timeout=5)
            self.stop(process)

        self.assertEqual(self.state(self.secondary_db)[0], [(1, "Milho")])
        silos, _, (sequence, event) = self.state(self.primary_db)
        self.assertEqual(silos, [])
        self.assertEqual(sequence, 1)
        self.assertIsNotNone(event)
        _, primary = self.start("primary", self.primary_db, secondary)
        self.assertEqual(self.success(primary, "listar_silos")["silos"],
                         [{"id": 1, "nome": "Milho"}])
        self.assertEqual(self.success(primary, "cadastrar_silo", nome="Trigo")["id"], 2)
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])


if __name__ == "__main__":
    unittest.main()
