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
REPLICA_STATE = "_estado_replica"
MUTATIONS = {
    "cadastrar_silo": ("silos", ("id", "nome")),
    "registrar_medicao": (
        "medicoes", ("id", "silo_id", "temperatura", "umidade", "registrada_em")
    ),
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
        state = db.execute("SELECT papel, evento FROM replicacao WHERE singleton = 1").fetchone()
        if state is not None and state["papel"] != role:
            raise ValueError("O banco já está associado a outro papel de servidor.")
        if role == "primary" and state["evento"] is not None:
            stage_legacy_event(db, json.loads(state["evento"]))


def stage_legacy_event(db, event):
    # No Checkpoint 2, a linha pendente ficava visível no banco do primário.
    # O evento durável preserva a linha inteira até a confirmação do secundário.
    table, _ = MUTATIONS[event["operacao"]]
    row = event["registro"]
    previous = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row["id"],)).fetchone()
    if previous is not None:
        if dict(previous) != row:
            raise ValueError("A linha local diverge do evento pendente.")
        db.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))
        LOG.info("primario migrou evento pendente do Checkpoint 2")


def encode_event(event):
    return json.dumps(event, sort_keys=True, allow_nan=False)


def insert_record(db, operation, row):
    record_id = integer(row, "id")
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
        is_write = operation in MUTATIONS
        with self.lock:
            with self.service.storage.connection() as db:
                state = db.execute(
                    "SELECT sequencia, evento FROM replicacao WHERE singleton = 1"
                ).fetchone()
            sequence = state["sequencia"]
            if state["evento"] is not None:
                try:
                    self.confirm(sequence, json.loads(state["evento"]))
                except RequestError:
                    if is_write:
                        raise
                    LOG.info("primario consulta em modo degradado sequencia=%s", sequence - 1)

            if not is_write:
                return self.service.execute_operation(operation, data)

            try:
                self.check_peer(REPLICA_STATE, {}, sequence)
            except (OSError, ProtocolError) as exc:
                LOG.warning("primario bloqueou nova escrita sequencia=%s: %s", sequence + 1, exc)
                raise RequestError(
                    "REPLICA_INDISPONIVEL",
                    "Nova escrita bloqueada. A réplica está indisponível ou fora de sincronia.",
                ) from exc

            sequence += 1
            result, event = self.prepare(sequence, operation, data)
            self.confirm(sequence, event)
            return result

    def prepare(self, sequence, operation, data):
        _, fields = MUTATIONS[operation]
        with self.service.storage.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Reutiliza validação, geração de ID e horário sem publicar a linha.
            db.execute("SAVEPOINT preparar")
            result = self.service.operations[operation](db, data)
            event = {"operacao": operation, "registro": {field: result[field] for field in fields}}
            db.execute("ROLLBACK TO preparar")
            db.execute("RELEASE preparar")
            db.execute("UPDATE replicacao SET sequencia = ?, evento = ? WHERE singleton = 1",
                       (sequence, encode_event(event)))
        return result, event

    def check_peer(self, operation, data, sequence):
        response = request(self.host, self.port, operation, {"chave": self.key, **data},
                           self.timeout)
        acknowledged = response.get("dados", {}).get("sequencia")
        if not response["ok"] or type(acknowledged) is not int or acknowledged != sequence:
            reason = response.get("erro", {}).get("codigo", "SEQUENCIA_INESPERADA")
            raise ProtocolError(str(reason))

    def confirm(self, sequence, event):
        LOG.info("primario enviando sequencia=%s operacao=%s", sequence, event["operacao"])
        try:
            self.check_peer(REPLICATE, {"sequencia": sequence, **event}, sequence)
        except (OSError, ProtocolError) as exc:
            LOG.warning("primario sem confirmacao sequencia=%s: %s", sequence, exc)
            raise RequestError(
                "REPLICA_INDISPONIVEL",
                "Há uma escrita pendente de confirmação. Consulte o estado após a recuperação.",
            ) from exc
        with self.service.storage.connection() as db:
            insert_record(db, event["operacao"], event["registro"])
            db.execute("UPDATE replicacao SET evento = NULL WHERE singleton = 1")
        LOG.info("primario confirmou sequencia=%s", sequence)


class Secondary:
    def __init__(self, service, key):
        self.service = service
        self.key = key

    def execute(self, request_data):
        operation = request_data.get("operacao")
        if operation in (REPLICATE, REPLICA_STATE):
            data = request_data.get("dados")
            self.check_key(data)
            return self.apply(data) if operation == REPLICATE else self.state()
        operation, data = self.service.parse_request(request_data)
        if operation in MUTATIONS:
            raise RequestError("SOMENTE_LEITURA", "Envie escritas ao servidor primário.")
        return self.service.execute_operation(operation, data)

    def check_key(self, data):
        key = data.get("chave") if isinstance(data, dict) else None
        if not isinstance(key, str) or not key.isascii() or not hmac.compare_digest(key, self.key):
            raise RequestError("REPLICACAO_NEGADA", "Chave de replicação inválida.")

    def state(self):
        with self.service.storage.connection() as db:
            state = db.execute("SELECT sequencia FROM replicacao WHERE singleton = 1").fetchone()
        return {"sequencia": state["sequencia"]}

    def apply(self, data):
        sequence = integer(data, "sequencia")
        operation = data.get("operacao")
        row = data.get("registro")
        if (not isinstance(operation, str) or operation not in MUTATIONS
                or not isinstance(row, dict) or set(row) != set(MUTATIONS[operation][1])):
            raise RequestError("REPLICACAO_INVALIDA", "Evento de replicação inválido.")
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
                    insert_record(db, operation, row)
                except UnicodeEncodeError as exc:
                    raise RequestError("REPLICACAO_INVALIDA", "Texto do evento inválido.") from exc
                db.execute("UPDATE replicacao SET sequencia = ?, evento = ? WHERE singleton = 1",
                           (sequence, event))
            else:
                raise RequestError("SEQUENCIA_INVALIDA", "Sequência ou conteúdo divergente.")
        LOG.info("secundario %s sequencia=%s operacao=%s",
                 "reconfirmou" if replay else "persistiu", sequence, operation)
        return {"sequencia": sequence}
