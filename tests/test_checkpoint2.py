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
from agrosilo.protocol import receive_message

HOST = "127.0.0.1"
KEY = "chave-integracao"


class Checkpoint2Tests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.primary_db = self.root / "primary.sqlite3"
        self.secondary_db = self.root / "secondary.sqlite3"

    def start(self, role, db, replica_port=9001):
        process = subprocess.Popen(
            [sys.executable, "-m", "agrosilo.server", "--role", role, "--port", "0",
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

    def test_unreachable_replica_keeps_single_pending_event_across_restart(self):
        with socket.socket() as unavailable:
            unavailable.bind((HOST, 0))
            missing_port = unavailable.getsockname()[1]
            process, primary = self.start("primary", self.primary_db, missing_port)
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Pendente")
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Bloqueado")
            self.failure("REPLICA_INDISPONIVEL", primary, "listar_silos")
            silos, _, (sequence, event) = self.state(self.primary_db)
            self.assertEqual(silos, [(1, "Pendente")])
            self.assertEqual(sequence, 1)
            self.assertIsNotNone(event)
            self.stop(process)

        _, secondary = self.start("secondary", self.secondary_db)
        self.assertEqual(self.success(secondary, "listar_silos")["silos"], [])
        _, primary = self.start("primary", self.primary_db, secondary)
        self.assertEqual(self.success(primary, "listar_silos")["silos"],
                         [{"id": 1, "nome": "Pendente"}])
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])
        self.assertEqual(self.state(self.primary_db)[2], (1, None))

    def test_applied_event_with_lost_ack_is_replayed_without_duplicate(self):
        _, secondary = self.start("secondary", self.secondary_db)

        def lose_ack(listener):
            conn, _ = listener.accept()
            with conn:
                message = receive_message(conn, 3)
                return self.success(secondary, message["operacao"], **message["dados"])

        with socket.socket() as proxy, ThreadPoolExecutor(max_workers=1) as worker:
            proxy.bind((HOST, 0))
            proxy.listen()
            proxy.settimeout(10)
            result = worker.submit(lose_ack, proxy)
            process, primary = self.start("primary", self.primary_db, proxy.getsockname()[1])
            self.failure("REPLICA_INDISPONIVEL", primary, "cadastrar_silo", nome="Milho")
            self.assertEqual(result.result(timeout=5), {"sequencia": 1})
            self.stop(process)

        self.assertEqual(self.state(self.secondary_db)[0], [(1, "Milho")])
        self.assertIsNotNone(self.state(self.primary_db)[2][1])
        _, primary = self.start("primary", self.primary_db, secondary)
        self.assertEqual(self.success(primary, "listar_silos")["silos"],
                         [{"id": 1, "nome": "Milho"}])
        self.assertEqual(self.success(primary, "cadastrar_silo", nome="Trigo")["id"], 2)
        self.assertEqual(self.state(self.primary_db)[:2], self.state(self.secondary_db)[:2])


if __name__ == "__main__":
    unittest.main()
