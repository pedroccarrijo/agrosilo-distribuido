"""Replicação síncrona em uma dupla de servidores com papéis fixos."""
import hmac
import json
import logging
import threading

from .client import request
from .protocol import ProtocolError
from .service import RequestError, integer, number

LOG = logging.getLogger(__name__)
REPLICATE = "_replicar"
WRITE_FIELDS = {
    "cadastrar_silo": ("id", "nome"),
    "registrar_medicao": ("id", "silo_id", "temperatura", "umidade", "registrada_em"),
}


def initialize_role(storage, role):
    with storage.connection() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS replicacao (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                papel TEXT NOT NULL,
                sequencia INTEGER NOT NULL DEFAULT 0,
                evento TEXT
            )
        """)
        if role != "standalone":
            db.execute("INSERT OR IGNORE INTO replicacao (singleton, papel) VALUES (1, ?)",
                       (role,))
        state = db.execute("SELECT papel FROM replicacao WHERE singleton = 1").fetchone()
        if state is not None and state["papel"] != role:
            raise ValueError("O banco já está associado a outro papel de servidor.")


def encode_event(event):
    return json.dumps(event, sort_keys=True, allow_nan=False)


class Primary:
    def __init__(self, service, host, port, timeout, key):
        self.service = service
        self.host = host
        self.port = port
        self.timeout = timeout
        self.key = key
        self.lock = threading.Lock()

    def execute(self, request_data):
        operation, data = self.service.parse_request(request_data)
        with self.lock:
            with self.service.storage.connection() as db:
                state = db.execute(
                    "SELECT sequencia, evento FROM replicacao WHERE singleton = 1"
                ).fetchone()
            sequence = state["sequencia"]
            if state["evento"] is not None:
                self.confirm(sequence, json.loads(state["evento"]))

            if operation not in WRITE_FIELDS:
                return self.service.execute_operation(operation, data)

            sequence += 1
            with self.service.storage.connection() as db:
                result = self.service.operations[operation](db, data)
                event = {"operacao": operation,
                         "registro": {field: result[field] for field in WRITE_FIELDS[operation]}}
                db.execute("UPDATE replicacao SET sequencia = ?, evento = ? WHERE singleton = 1",
                           (sequence, encode_event(event)))
            self.confirm(sequence, event)
            return result

    def confirm(self, sequence, event):
        LOG.info("primario enviando sequencia=%s operacao=%s", sequence, event["operacao"])
        try:
            response = request(self.host, self.port, REPLICATE,
                               {"chave": self.key, "sequencia": sequence, **event}, self.timeout)
            acknowledged = response.get("dados", {}).get("sequencia")
            if not response["ok"] or type(acknowledged) is not int or acknowledged != sequence:
                reason = response.get("erro", {}).get("codigo", "ACK_INVALIDO")
                raise ProtocolError(str(reason))
        except (OSError, ProtocolError) as exc:
            LOG.warning("primario sem confirmacao sequencia=%s: %s", sequence, exc)
            raise RequestError(
                "REPLICA_INDISPONIVEL",
                "Escrita pendente de confirmação da réplica. Consulte o estado após a recuperação.",
            ) from exc

        with self.service.storage.connection() as db:
            db.execute("UPDATE replicacao SET evento = NULL WHERE singleton = 1")
        LOG.info("primario confirmou sequencia=%s", sequence)


class Secondary:
    def __init__(self, service, key):
        self.service = service
        self.key = key

    def execute(self, request_data):
        if request_data.get("operacao") == REPLICATE:
            return self.apply(request_data.get("dados"))
        operation, data = self.service.parse_request(request_data)
        if operation in WRITE_FIELDS:
            raise RequestError("SOMENTE_LEITURA", "Envie escritas ao servidor primário.")
        return self.service.execute_operation(operation, data)

    def apply(self, data):
        key = data.get("chave") if isinstance(data, dict) else None
        if not isinstance(key, str) or not key.isascii() or not hmac.compare_digest(key, self.key):
            raise RequestError("REPLICACAO_NEGADA", "Chave de replicação inválida.")
        sequence = integer(data, "sequencia")
        operation = data.get("operacao")
        row = data.get("registro")
        if (not isinstance(operation, str) or operation not in WRITE_FIELDS
                or not isinstance(row, dict) or set(row) != set(WRITE_FIELDS[operation])):
            raise RequestError("REPLICACAO_INVALIDA", "Evento de replicação inválido.")
        record_id = integer(row, "id")
        try:
            event = encode_event({"operacao": operation, "registro": row})
        except (ValueError, RecursionError) as exc:
            raise RequestError("REPLICACAO_INVALIDA", "Valores do evento inválidos.") from exc
        with self.service.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute(
                "SELECT sequencia, evento FROM replicacao WHERE singleton = 1"
            ).fetchone()
            if sequence == state["sequencia"] and event == state["evento"]:
                replay = True
            elif sequence == state["sequencia"] + 1:
                replay = False
                try:
                    self.insert_record(db, operation, record_id, row)
                except UnicodeEncodeError as exc:
                    raise RequestError("REPLICACAO_INVALIDA", "Texto do evento inválido.") from exc
                db.execute("UPDATE replicacao SET sequencia = ?, evento = ? WHERE singleton = 1",
                           (sequence, event))
            else:
                raise RequestError("SEQUENCIA_INVALIDA", "Sequência ou conteúdo divergente.")
        LOG.info("secundario %s sequencia=%s operacao=%s",
                 "reconfirmou" if replay else "persistiu", sequence, operation)
        return {"sequencia": sequence}

    @staticmethod
    def insert_record(db, operation, record_id, row):
        if operation == "cadastrar_silo":
            name = row["nome"]
            if not isinstance(name, str) or not 1 <= len(name) <= 80:
                raise RequestError("REPLICACAO_INVALIDA", "Nome de silo inválido.")
            db.execute("INSERT INTO silos (id, nome) VALUES (?, ?)", (record_id, name))
        else:
            timestamp = row["registrada_em"]
            if not isinstance(timestamp, str) or not 1 <= len(timestamp) <= 32:
                raise RequestError("REPLICACAO_INVALIDA", "Data de medição inválida.")
            db.execute("""
                INSERT INTO medicoes (id, silo_id, temperatura, umidade, registrada_em)
                VALUES (?, ?, ?, ?, ?)
                """, (record_id, integer(row, "silo_id"),
                      number(row, "temperatura", -273.15, 1000),
                      number(row, "umidade", 0, 100), timestamp))
