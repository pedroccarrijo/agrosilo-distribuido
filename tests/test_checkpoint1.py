import json
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agrosilo.client import request
from agrosilo.protocol import MAX_FRAME, receive_message

HOST = "127.0.0.1"


class Checkpoint1Tests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.db = Path(workspace.name) / "test.sqlite3"
        self.start_server()

    def start_server(self):
        process = subprocess.Popen(
            [sys.executable, "-m", "agrosilo.server", "--port", "0", "--db", str(self.db),
             "--timeout", "0.5", "--max-temperatura", "28", "--max-umidade", "60"],
            stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop_server, process)
        self.process = process
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        line = ready.get(timeout=10)
        self.assertIn("ouvindo", line)
        self.port = int(line.rsplit(":", 1)[1])

    @staticmethod
    def stop_server(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()

    def call(self, operation, **data):
        response = request(HOST, self.port, operation, data)
        self.assertTrue(response["ok"], response)
        return response["dados"]

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "agrosilo.client",
             "--port", str(self.port), *args],
            capture_output=True, encoding="utf-8", timeout=10,
        )

    def test_client_process_and_simulated_sensor(self):
        create = self.cli("cadastrar_silo", "Grãos")
        self.assertEqual(create.returncode, 0, create.stderr)
        silo = json.loads(create.stdout)["dados"]
        self.assertEqual(silo["nome"], "Grãos")
        result = self.cli("simular", str(silo["id"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        measurement = json.loads(result.stdout)["dados"]
        self.assertTrue(20 <= measurement["temperatura"] <= 38)
        self.assertEqual(self.call("consultar_silo", silo_id=silo["id"])["ultima_medicao"],
                         measurement)

    def test_history_alerts_and_persistence_after_restart(self):
        silo_id = self.call("cadastrar_silo", nome="Milho")["id"]
        self.assertIsNone(self.call("consultar_silo", silo_id=silo_id)["ultima_medicao"])
        normal = self.call("registrar_medicao", silo_id=silo_id, temperatura=28, umidade=60)
        alert = self.call("registrar_medicao", silo_id=silo_id, temperatura=29, umidade=61)
        self.assertEqual(normal["status"], "normal")
        self.assertEqual(alert["alertas"], ["temperatura", "umidade"])
        self.assertEqual(alert["limites_demonstrativos"], {"temperatura": 28, "umidade": 60})
        self.stop_server(self.process)
        self.start_server()
        page = self.call("consultar_medicoes", silo_id=silo_id, limite=1)
        self.assertEqual(page["medicoes"], [alert])
        page2 = self.call("consultar_medicoes", silo_id=silo_id,
                          antes_id=page["proximo_antes_id"])
        self.assertEqual(page2, {"medicoes": [normal], "proximo_antes_id": None})

    def test_two_clients_with_overlapping_connections(self):
        with socket.create_connection((HOST, self.port), timeout=3) as first:
            first.sendall(b'{"operacao":"cadastrar_silo",')
            second = self.call("cadastrar_silo", nome="Segundo")
            first.sendall(b'"dados":{"nome":"Primeiro"}}\n')
            response = receive_message(first, 3)
        self.assertTrue(response["ok"], response)
        self.assertNotEqual(response["dados"]["id"], second["id"])

    def test_simultaneous_writes_and_silo_pagination(self):
        barrier = threading.Barrier(4, timeout=5)

        def write(index):
            barrier.wait()
            return self.call("cadastrar_silo", nome=f"Silo {index}")["id"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = sorted(pool.map(write, range(4)))
        page = self.call("listar_silos", limite=2)
        following = self.call("listar_silos", apos_id=page["proximo_apos_id"])
        self.assertEqual([row["id"] for row in page["silos"] + following["silos"]], ids)
        self.assertIsNone(following["proximo_apos_id"])

    def test_invalid_frames_and_premature_disconnect(self):
        for frame in (b'{broken}\n', b'[]\n', b'\xff\n', b'x' * (MAX_FRAME + 1),
                      b'{"n":NaN}\n', b'{"incompleto":'):
            with self.subTest(frame=frame[:30]):
                with socket.create_connection((HOST, self.port), timeout=3) as conn:
                    conn.sendall(frame)
                    conn.shutdown(socket.SHUT_WR)
                    self.assertEqual(receive_message(conn, 3)["erro"]["codigo"],
                                     "MENSAGEM_INVALIDA")
        with socket.create_connection((HOST, self.port), timeout=3):
            pass
        self.assertEqual(self.call("listar_silos")["silos"], [])

    def test_invalid_domain_requests(self):
        cases = [
            ("desconhecida", {}, "OPERACAO_DESCONHECIDA"),
            ("cadastrar_silo", {"nome": " "}, "DADOS_INVALIDOS"),
            ("consultar_silo", {"silo_id": True}, "DADOS_INVALIDOS"),
            ("consultar_silo", {"silo_id": 999}, "SILO_INEXISTENTE"),
            ("registrar_medicao", {"silo_id": 999, "temperatura": 22, "umidade": 101},
             "DADOS_INVALIDOS"),
        ]
        for operation, data, code in cases:
            with self.subTest(operation=operation, data=data):
                self.assertEqual(request(HOST, self.port, operation, data)["erro"]["codigo"], code)

    def test_server_timeout_and_client_connection_refused(self):
        with socket.create_connection((HOST, self.port), timeout=3) as conn:
            conn.sendall(b'{')
            self.assertEqual(receive_message(conn, 3)["erro"]["codigo"], "TIMEOUT")
            self.assertIsNone(receive_message(conn, 3))
        self.stop_server(self.process)
        result = self.cli("listar_silos")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Falha de conexão", result.stderr)

    def test_client_read_timeout_and_unexpected_eof(self):
        with socket.socket() as listener:
            listener.bind((HOST, 0))
            listener.listen()
            listener.settimeout(3)
            port = listener.getsockname()[1]
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(request, HOST, port, "listar_silos", timeout=0.2)
                conn, _ = listener.accept()
                with conn, self.assertRaises(TimeoutError):
                    pending.result(timeout=3)
                pending = pool.submit(request, HOST, port, "listar_silos", timeout=3)
                conn, _ = listener.accept()
                with conn:
                    self.assertEqual(receive_message(conn, 3)["operacao"], "listar_silos")
                with self.assertRaisesRegex(ValueError, "sem responder"):
                    pending.result(timeout=3)


if __name__ == "__main__":
    unittest.main()
