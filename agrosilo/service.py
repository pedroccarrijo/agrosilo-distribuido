"""Operações de domínio e validação das entradas."""
import math
from datetime import datetime, timezone


class RequestError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def integer(data, key, minimum=1, maximum=2**63 - 1, default=None):
    value = data.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise RequestError("DADOS_INVALIDOS", f"{key} deve ser um inteiro entre {minimum} e {maximum}.")
    return value


def number(data, key, minimum, maximum):
    value = data.get(key)
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise RequestError("DADOS_INVALIDOS", f"{key} deve ser um número entre {minimum} e {maximum}.")
    return value


class AgroSilo:
    def __init__(self, storage, max_temperatura, max_umidade):
        if not math.isfinite(max_temperatura) or not -273.15 <= max_temperatura <= 1000:
            raise ValueError("Limite de temperatura fora da faixa aceita.")
        if not 0 <= max_umidade <= 100:
            raise ValueError("Limite de umidade fora da faixa aceita.")
        self.storage = storage
        self.limits = {"temperatura": max_temperatura, "umidade": max_umidade}
        self.operations = {
            "cadastrar_silo": self.create_silo,
            "consultar_silo": self.get_silo,
            "listar_silos": self.list_silos,
            "registrar_medicao": self.create_measurement,
            "consultar_medicoes": self.history,
        }

    def execute(self, request):
        operation = request.get("operacao")
        data = request.get("dados", {})
        if not isinstance(operation, str) or not isinstance(data, dict):
            raise RequestError("DADOS_INVALIDOS", "Informe operacao (texto) e dados (objeto).")
        if operation not in self.operations:
            raise RequestError("OPERACAO_DESCONHECIDA", "Operação desconhecida.")
        with self.storage.connection() as db:
            return self.operations[operation](db, data)

    def create_silo(self, db, data):
        name = data.get("nome")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise RequestError("DADOS_INVALIDOS", "Nome deve ter de 1 a 80 caracteres.")
        name = name.strip()
        try:
            name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RequestError("DADOS_INVALIDOS", "Nome contém Unicode inválido.") from exc
        cursor = db.execute("INSERT INTO silos (nome) VALUES (?)", (name,))
        return {"id": cursor.lastrowid, "nome": name}

    def get_silo(self, db, data):
        silo_id = integer(data, "silo_id")
        silo = db.execute("SELECT * FROM silos WHERE id = ?", (silo_id,)).fetchone()
        if silo is None:
            raise RequestError("SILO_INEXISTENTE", "Silo não encontrado.")
        latest = db.execute(
            "SELECT * FROM medicoes WHERE silo_id = ? ORDER BY id DESC LIMIT 1", (silo_id,)
        ).fetchone()
        return {**dict(silo), "ultima_medicao": self.assess(latest) if latest else None}

    def list_silos(self, db, data):
        limit = integer(data, "limite", maximum=15, default=15)
        after = integer(data, "apos_id", minimum=0, default=0)
        rows = db.execute(
            "SELECT * FROM silos WHERE id > ? ORDER BY id LIMIT ?", (after, limit + 1)
        ).fetchall()
        return {"silos": [dict(row) for row in rows[:limit]],
                "proximo_apos_id": rows[limit - 1]["id"] if len(rows) > limit else None}

    def create_measurement(self, db, data):
        silo_id = integer(data, "silo_id")
        measurement = {
            "silo_id": silo_id,
            "temperatura": number(data, "temperatura", -273.15, 1000),
            "umidade": number(data, "umidade", 0, 100),
            "registrada_em": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        if db.execute("SELECT id FROM silos WHERE id = ?", (silo_id,)).fetchone() is None:
            raise RequestError("SILO_INEXISTENTE", "Silo não encontrado.")
        cursor = db.execute("""
            INSERT INTO medicoes (silo_id, temperatura, umidade, registrada_em)
            VALUES (:silo_id, :temperatura, :umidade, :registrada_em)
            """, measurement)
        return self.assess({"id": cursor.lastrowid, **measurement})

    def history(self, db, data):
        silo_id = integer(data, "silo_id")
        limit = integer(data, "limite", maximum=40, default=20)
        before = integer(data, "antes_id") if "antes_id" in data else None
        if db.execute("SELECT id FROM silos WHERE id = ?", (silo_id,)).fetchone() is None:
            raise RequestError("SILO_INEXISTENTE", "Silo não encontrado.")
        query = "SELECT * FROM medicoes WHERE silo_id = ?"
        params = [silo_id]
        if before is not None:
            query += " AND id < ?"
            params.append(before)
        rows = db.execute(query + " ORDER BY id DESC LIMIT ?", (*params, limit + 1)).fetchall()
        return {"medicoes": [self.assess(row) for row in rows[:limit]],
                "proximo_antes_id": rows[limit - 1]["id"] if len(rows) > limit else None}

    def assess(self, row):
        alerts = [field for field, limit in self.limits.items() if row[field] > limit]
        return {**dict(row), "status": "alerta" if alerts else "normal",
                "alertas": alerts, "limites_demonstrativos": self.limits}
