"""Cliente de terminal e função reutilizável para o protocolo AgroSilo."""
import argparse
import json
import random
import socket
import sys

from .protocol import ProtocolError, receive_message, send_message


def request(host, port, operation, data=None, timeout=5):
    with socket.create_connection((host, port), timeout=timeout) as connection:
        send_message(connection, {"operacao": operation, "dados": data if data is not None else {}},
                     timeout)
        response = receive_message(connection, timeout)
    if response is None:
        raise ProtocolError("Servidor encerrou a conexão sem responder.")
    if response.get("ok") is True and isinstance(response.get("dados"), dict):
        return response
    if response.get("ok") is False and isinstance(response.get("erro"), dict):
        return response
    raise ProtocolError("Formato de resposta inesperado.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--timeout", type=float, default=5)
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("cadastrar_silo").add_argument("nome")
    commands.add_parser("consultar_silo").add_argument("silo_id", type=int)
    listing = commands.add_parser("listar_silos")
    listing.add_argument("--limite", type=int)
    listing.add_argument("--apos-id", type=int)
    measurement = commands.add_parser("registrar_medicao")
    measurement.add_argument("silo_id", type=int)
    measurement.add_argument("temperatura", type=float)
    measurement.add_argument("umidade", type=float)
    history = commands.add_parser("consultar_medicoes")
    history.add_argument("silo_id", type=int)
    history.add_argument("--limite", type=int)
    history.add_argument("--antes-id", type=int)
    commands.add_parser("simular").add_argument("silo_id", type=int)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout deve estar no intervalo (0, 300] segundos.")
    if not 1 <= args.port <= 65535:
        parser.error("--port deve estar entre 1 e 65535.")

    data = {key: value for key, value in vars(args).items()
            if key not in {"host", "port", "timeout", "operation"} and value is not None}
    operation = args.operation
    if operation == "simular":
        operation = "registrar_medicao"
        data.update(temperatura=round(random.uniform(20, 38), 1),
                    umidade=round(random.uniform(45, 85), 1))

    try:
        response = request(args.host, args.port, operation, data, args.timeout)
    except TimeoutError:
        print("Tempo de espera esgotado.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Falha de conexão com o servidor: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Erro de mensagem: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
